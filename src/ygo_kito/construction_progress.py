"""Pre-CB construction gate and serializable optimization continuation."""
from copy import deepcopy
import math

from .build_contracts import DeckParts, digest
from .validation import ContractError

FUNCTIONAL_GATE_VERSION = 'construction-before-cb-v3'
GATE_VERSION = FUNCTIONAL_GATE_VERSION
REFERENCE_STAGE_VERSION = 'construction-reference-stage-v1'
FEEDBACK_HARD_CHECK_VERSION = 'construction-feedback-hard-check-v1'


def feedback_hard_check(task, deck, assets, *, candidate_version=1):
    """Post-admission hard check for feedback revisions: legality and task hard constraints only, 0 static scoring."""
    from collections import Counter
    reasons = []
    if not isinstance(deck, DeckParts):
        try:
            deck = DeckParts.from_dict(deck)
        except ContractError as error:
            reasons.append('invalid_deck_structure:' + str(error))
            return dict(version=FEEDBACK_HARD_CHECK_VERSION, passed=False, reasons=reasons,
                task_sha256=task.sha256, deck_sha256=digest(deck),
                candidate_version=max(1, int(candidate_version or 1)), static_scoring_calls=0)
    try:
        assets.validate(task, deck)
    except ContractError as error:
        reasons.append('original_constraints:' + str(error))
    main_counts = Counter(deck.main)
    present_ids = set(deck.main + deck.extra)
    route_goal = task.goal.get('route_goal')
    if isinstance(route_goal, dict):
        if route_goal.get('card_id') not in present_ids:
            reasons.append('original_goal:route_goal_card_missing')
        opening = Counter((route_goal.get('starting_conditions') or {}).get('requires_opening_hand', ()))
        if opening - main_counts:
            reasons.append('original_goal:opening_hand_missing')
    for key in ('required_activations', 'required_chain_resolutions'):
        missing = sorted(set(task.goal.get(key, ())) - present_ids)
        if missing:
            reasons.append(f'original_goal:{key}_missing:' + ','.join(map(str, missing)))
    return dict(
        version=FEEDBACK_HARD_CHECK_VERSION,
        passed=not reasons,
        reasons=reasons,
        task_sha256=task.sha256,
        deck_sha256=digest(deck.to_dict()),
        candidate_version=max(1, int(candidate_version or 1)),
        static_scoring_calls=0,
    )


def is_initial_admitted(state, task_sha256):
    """Return whether this task has already completed initial S3-S5 admission."""
    if not isinstance(state, dict):
        return False
    initial = state.get('initial_admission')
    if (isinstance(initial, dict)
            and initial.get('version') == FUNCTIONAL_GATE_VERSION
            and initial.get('task_sha256') == task_sha256
            and (initial.get('gate') or {}).get('status') == 'passed'
            and initial.get('deck_sha256') == (initial.get('gate') or {}).get('deck_sha256')):
        return True
    gate = state.get('gate')
    return (
        state.get('status') == 'passed'
        and isinstance(gate, dict)
        and gate.get('version') == FUNCTIONAL_GATE_VERSION
        and gate.get('status') == 'passed'
        and gate.get('task_sha256') == task_sha256
    )


def goal_effect_draft(session, *, record=False):
    """Recover the goal graph actually handed to construction, including after a pause."""
    if record:
        logic_sha256 = session.logic.sha256
    else:
        marker = next((event for event in reversed(session.history)
                       if event.get('stage') == 'effect_draft_handoff'), None)
        if marker is None:
            return None
        logic_sha256 = marker['logic_sha256']
    event = next((row for row in reversed(session.history) if row.get('stage') == 1
                  and row.get('role') == 'build_goal' and row.get('logic_sha256') == logic_sha256), None)
    if event is None:
        return None
    logic = event['logic']
    if getattr(session, 'construction_request', None) and not any(
            tag['dimension'] == 'effect' for node in logic['nodes'] for tag in node['tags']):
        return None
    if record:
        session.history.append(dict(stage='effect_draft_handoff', logic_sha256=logic_sha256))
    return dict(logic=deepcopy(logic), logic_sha256=logic_sha256,
                goal_sha256=session.goal_sha256, unfilled=dict(session.task.sizes))


def compact_optimizer_phase(phase, *, task=None, _comparisons=None):
    """Keep round results without inventories, reversible edits, or search work."""
    if phase is None:
        return None
    keys = ('phase_number', 'role', 'responsibility', 'optimization_iteration',
            'input_candidate_version', 'output_candidate_version', 'parameter_update_performed',
            'acceptance', 'stage_1', 'effect_draft', 'unfilled', 'input_deck_sha256', 'proposal_deck_sha256',
            'reference_feedback', 'admission_mode', 'static_scoring_calls', 'feedback_hard_check',
            'feedback_duel_comparison')
    saved = {key: phase[key] for key in keys if key in phase}
    if 'stage_2' in phase:
        saved['stage_2'] = {'status': phase['stage_2'].get('status')}
    if phase.get('graph_model_selection') is not None:
        selection = phase['graph_model_selection']
        keys = ('selection', 'scores', 'selected_index', 'graph_sha256', 'model_sha256',
                'graph_role_update_count', 'binding_counterexample_exploration')
        saved['graph_model_selection'] = {key: selection[key] for key in keys if key in selection}
    for key in ('input_deck', 'proposal_deck'):
        if phase.get(key) is not None:
            saved[key + '_sha256'] = digest(phase[key])
    gate = phase.get('gate')
    if gate:
        saved['gate'] = {k: gate[k] for k in ('status', 'outcome', 'reasons', 'deck_sha256',
                                              'candidate_version', 'evaluation_complete') if k in gate}
    stage = phase.get('stage_3')
    if stage is None:
        return saved
    keys = ('status', 'selection_complete', 'selected_attempt_index', 'evaluation_cursor',
            'ranking', 'candidate_count', 'strict_quality_pairs', 'engine_validation_performed')
    reduced = {key: stage[key] for key in keys if key in stage}
    if 'attempts' in stage:
        reduced['engine_validation_performed'] = any(
            attempt.get('engine_validation', {}).get('status', 'not_run') != 'not_run'
            for attempt in stage['attempts'])
    trace = stage.get('candidate_trace')
    if trace is not None:
        keys = ('candidate_index', 'deck_sha256', 'strategy', 'model_score_uncalibrated',
                'evaluation_status', 'quality_evaluation_id', 'status', 'selected', 'reference_delta',
                'graph_binding_unresolved')
        candidates = []
        for row in trace.get('candidates', ()):
            item = {key: row[key] for key in keys if key in row}
            inventory = row.get('recognition_inventory')
            if inventory is not None:
                item['deck_sha256'] = digest(inventory)
            quality = row.get('quality_summary')
            if quality:
                item['quality_summary'] = {key: quality[key] for key in
                    ('value', 'min', 'max', 'complete', 'scope_complete', 'unit') if key in quality}
            candidates.append(item)
        generation = trace.get('generation', {})
        counts = {key: value for key, value in generation.items() if type(value) is int}
        reduced['candidate_trace'] = dict(candidates=candidates, generation=counts,
            candidate_order=trace.get('candidate_order'), selected_candidate_index=trace.get('selected_candidate_index'))
        reduced['candidate_count'] = len(candidates)
    if task is not None and stage.get('learning_candidates'):
        from .construction_learning import quality_pair_receipts
        reduced['strict_quality_pairs'] = quality_pair_receipts(task, stage, _comparisons=_comparisons)
    summary = phase.get('quality_summary')
    if summary:
        saved['quality_summary'] = {key: summary[key] for key in
            ('value', 'min', 'max', 'complete', 'unit', 'evaluation_id') if key in summary}
    saved['stage_3'] = reduced
    return saved


def compact_construction_candidate(candidate):
    if candidate is None:
        return None
    return {key: value for key, value in candidate.items()
            if key not in ('changes', 'generation', 'protected_package')}


def compact_completed_progress(state):
    """Discard spent candidate inventories; the active batch can still resume."""
    state['candidate'] = compact_construction_candidate(state['candidate'])
    state['retained_candidates'] = []
    if state['candidate_version'] > 1:
        state.pop('skeleton', None)
    state['last_optimizer_phase'] = compact_optimizer_phase(state.get('last_optimizer_phase'))


def construction_report(result):
    """The kernel owns the resumable work; the report keeps the working result."""
    report = {key: value for key, value in result.items()
              if key not in ('continuation', 'retained_candidates', 'verified_best')}
    if report.get('best') is not None:
        report.pop('construction_candidate', None)
    return report


def invalidate_reference_evaluation(state):
    reference = state.get('reference_evaluation')
    if reference is not None:
        state['stale_reference_evaluation'] = reference
    state.update(reference_evaluation=None, reference_binding=None)
    state.pop('reference_feedback', None)


def _reopen_reference_batch(state):
    stage = state.get('pending_reference')
    if stage and stage.get('version') == REFERENCE_STAGE_VERSION:
        state['pending_quality'] = dict(stage['candidate_batch'], comparison_progress=None)
        state['pending_phase'].pop('stage_3', None)
    state['pending_reference'] = None


def gate_outcome(gate):
    """Classify the existing Gate evidence, without a second score source."""
    if not gate:
        return 'not_evaluated'
    if gate.get('status') == 'passed':
        return 'passed'
    reasons = gate.get('reasons', ())
    configuration = ('quality_policy_unconfigured', 'quality_assets_changed', 'reference_invalid:',
        'reference_score_nonpositive', 'quality_binding_', 'reference_binding_')
    if any(r.startswith(configuration) for r in reasons):
        return 'configuration_error'
    if any('calculation_budget' in r or 'evaluation_budget' in r for r in reasons):
        return 'calculation_pending'
    incomplete = any(any(word in r for word in ('incomplete','unknown','missing','unresolved')) for r in reasons)
    failed = gate.get('status') == 'failed' or any(
        r.startswith('original_constraints:') or r.endswith(':failed') for r in reasons)
    if failed and not incomplete:
        return 'failed'
    return 'semantic_unimplemented' if reasons else 'not_evaluated'


def specified_course_reference(period_id, theme_id):
    """The user's two historical reference requests, unrelated to scoring rules."""
    requests = {('2022-07', 'setcode-181'):'main-01-source-v1',
        ('2022-10', 'setcode-181'):'main-02-source-v2'}
    period_id = {'2207':'2022-07', '2210':'2022-10'}.get(period_id, period_id)
    return requests.get((period_id, theme_id))


def host_construction_quality(task, *, period_id=None, theme_id=None, catalog=None,
                              theme=None, goal_tags=(), reference_id=None, interruption_bonus=False):
    """Fix automatic goals before candidate generation; references are explicit."""
    from .construction_quality import (
        FUNCTIONAL_QUALITY_VERSION, FUNCTIONAL_QUALITY_VERSION_V5, FUNCTION_DICTIONARY_VERSION, FUNCTIONAL_SCOPE,
        INTERRUPTION_HAS_WEIGHT, INTERRUPTION_SUPPORTED_WEIGHT,
    )
    from .construction_theme import derive_theme_profile, automatic_rules
    if type(interruption_bonus) is not bool:
        raise ContractError('interruption_bonus requires a bool')
    profile = derive_theme_profile(task, catalog, theme=theme, theme_id=theme_id, goal_tags=goal_tags)
    quality_spec = dict(
        evaluator_version=FUNCTIONAL_QUALITY_VERSION_V5 if interruption_bonus else FUNCTIONAL_QUALITY_VERSION,
        function_dictionary_version=FUNCTION_DICTIONARY_VERSION, theme_rules=automatic_rules(profile),
        theme_profile=profile,
        side_directions={'going_first': .5, 'going_second': .5}, required_scope=list(FUNCTIONAL_SCOPE),
    )
    if interruption_bonus:
        quality_spec['interruption_bonus'] = {
            'has_interruption_weight': INTERRUPTION_HAS_WEIGHT,
            'supported_interruption_weight': INTERRUPTION_SUPPORTED_WEIGHT,
        }
    policy = dict(version='construction-host-functional-v2', source='host:2026-11-08-construction-formal-plan',
        metrics=[], quality=quality_spec, **{'pass': {'mode': 'none'}})
    reference = None
    ref_id = reference_id or specified_course_reference(period_id, theme_id)
    if ref_id:
        import json
        from pathlib import Path
        from .agent_registry import identifier
        identifier(ref_id)
        path = Path(__file__).resolve().parents[2]/'configs'/'user-deck-references'/(ref_id+'.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        deck = DeckParts.from_dict(data['deck'])
        if data.get('reference_id') != ref_id or data.get('normalized_deck_sha256') != digest(deck.to_dict()):
            raise ContractError('specified construction reference listing binding differs')
        source = 'configs/user-deck-references/'+ref_id+'.json'
        reference = dict(reference_id=ref_id,source=source,environment=deepcopy(task.environment),deck=deck.to_dict())
        policy['pass'] = dict(mode='reference_ratio',minimum_reference_ratio=.8,
            reference=dict(reference_id=ref_id,deck_sha256=digest(deck.to_dict()),source=source))
    return quality_policy(policy), reference


class ConstructionSuspended(ContractError):
    safe_boundary_saved = False
    pause_requested = True

    def __init__(self, result):
        self.result = result
        super().__init__('Construction suspended: ' + result.get('stop_reason', 'not_passed'))


def quality_policy(value):
    """Thresholds are explicit host input, never inferred from a model score."""
    from .construction_quality import pass_policy, quality_config
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) - {'version', 'source', 'metrics', 'quality', 'pass'}
            or not {'version', 'source', 'metrics'} <= set(value)
            or any(not isinstance(value[k], str) or not value[k].strip() for k in ('version', 'source'))
            or not isinstance(value['metrics'], list) or len(value['metrics']) > 32
            # An empty metric list is a complete policy only through its pass line.
            or (not value['metrics'] and value.get('pass') is None)):
        raise ContractError('explicit versioned construction quality metrics required')
    for row in value['metrics']:
        if (not isinstance(row, dict) or set(row) != {'path', 'operator', 'threshold'}
                or not isinstance(row['path'], list) or not row['path']
                or row['path'][0] not in ('axis', 'relations', 'quality')
                or any(not isinstance(p, str) or not p for p in row['path'])
                or row['operator'] not in ('ge', 'le')
                or type(row['threshold']) not in (int, float) or not math.isfinite(row['threshold'])):
            raise ContractError('quality metric must name a layer value and finite threshold')
    quality_config(value.get('quality'))
    pass_policy(value.get('pass'))
    if any(row['path'][0] == 'quality' and row['path'][1:] not in (
            ['score', 'value'], ['score', 'lower'], ['score', 'upper']) for row in value['metrics']):
        raise ContractError('legacy percentage metrics cannot enter functional policy')
    return deepcopy(value)


def _quality_source(value, path):
    """Read one declared metric path; quality paths index the quality record."""
    value = value[path[0]] if path[0] != 'quality' else value
    for part in path[1:]:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _quality_binding(policy, quality, deck, comparisons=None):
    """Bind a quality record to this policy, deck and evaluation version."""
    from .construction_quality import quality_config
    if policy is None:
        return {'required': False}
    declared = (policy.get('quality') is not None or policy.get('pass') is not None
                or any(row['path'][0] == 'quality' for row in policy['metrics']))
    if not declared:
        if quality is not None:
            raise ContractError('quality evaluation supplied without a quality policy')
        return {'required': False}
    if quality is None:
        return {'required': True, 'present': False}
    from .construction_quality import (
        FUNCTIONAL_QUALITY_VERSION, SUPPORTED_FUNCTIONAL_QUALITY_VERSIONS, EvaluationComparisons,
    )
    expected_version = (policy.get('quality') or {}).get('evaluator_version') or FUNCTIONAL_QUALITY_VERSION
    if (not isinstance(quality, dict) or quality.get('version') not in SUPPORTED_FUNCTIONAL_QUALITY_VERSIONS
            or quality.get('version') != expected_version):
        raise ContractError('legacy quality requires semantic reevaluation')
    if (not isinstance(quality, dict) or quality.get('layer') != 'quality'
            or quality.get('policy_version') != policy['version']
            or quality.get('quality_config_sha256') != digest(quality_config(policy.get('quality')))):
        raise ContractError('quality evaluation belongs to another policy')
    if quality.get('deck_sha256') != digest(deck.to_dict()):
        raise ContractError('quality evaluation belongs to another candidate')
    total = quality['total']
    (comparisons or EvaluationComparisons()).bind(quality)
    from .construction_layer_flow import NORMALIZATION_VERSION
    if quality.get('normalization_version') != NORMALIZATION_VERSION:
        raise ContractError('quality normalization version requires reevaluation')
    if quality.get('function_dictionary_version') != policy['quality']['function_dictionary_version']:
        raise ContractError('quality function dictionary version requires reevaluation')
    if quality.get('policy_sha256') != digest(policy):
        raise ContractError('functional quality belongs to another fixed policy')
    return dict(required=True, present=True, complete=quality['complete'],
        scope_complete=quality['scope_complete'], evaluation_id=quality['evaluation_id'],
        policy_sha256=quality['policy_sha256'], asset_version=quality['asset_version'],
        normalization_version=quality['normalization_version'],
        facts_sha256=quality['facts_sha256'], logic_sha256=quality['logic_sha256'],
        value=quality['score']['value'], min=quality['score']['lower'], max=quality['score']['upper'],
        unit='functional_log2', deferred=quality['deferred'], unknown_items=quality['unknowns'],
        partial_items=total['partial_items'], total_status=total['status'])


def _functional_gate(task, deck, assets, evaluation, policy, candidate_version, quality,
                     reference_quality, comparisons, *, reference_validated=False):
    from .construction_inventory import InventoryDependencies
    from .effect_mechanisms import MechanismCatalog
    reasons, metrics = [], []
    try:
        assets.validate(task, deck)
    except ContractError as error:
        reasons.append('original_constraints:' + str(error))
    if evaluation is None:
        reasons.append('layer_evaluation_missing')
    elif (evaluation['axis']['inventory'] != deck.to_dict()
          or digest(evaluation['axis']['task']) != task.sha256):
        raise ContractError('functional gate layers belong to another task/candidate')
    binding = _quality_binding(policy, quality, deck, comparisons)
    if quality is None:
        reasons.append('quality_evaluation_missing')
    else:
        if quality['task_sha256'] != task.sha256 or (evaluation is not None
                and quality['logic_sha256'] != digest(evaluation['axis'].get('logic'))):
            raise ContractError('functional gate quality task/logic binding differs')
        from .construction_layer_flow import functional_asset_version
        if quality['asset_version'] != functional_asset_version(MechanismCatalog(assets, task.pool)):
            reasons.append('quality_assets_changed')
        if not quality['complete']:
            reasons.append('quality_evaluation_incomplete')
        reasons.extend('card_effect_coverage_unresolved:' + key for key in quality['total']['partial_items'])
        reasons.extend('quality_scope_unresolved:' + scope for scope in quality['deferred'])
        for row in quality['hard_requirements']:
            if row['status'] != 'satisfied':
                reasons.append('required_function:' + row['requirement_id'] + ':' + row['status'])
    # All optional deficits remain available for repair; only original hard
    # requirements above veto admission independently of S.
    if getattr(assets, "rule_authority", None) == "locked_period_core":
        dependencies = dict(kind="native_construction_inventory",
            uses=(quality or {}).get("condition_applicability", []),
            uncovered_cards=(quality or {}).get("total", {}).get("partial_items", []))
    else:
        dependencies = InventoryDependencies(MechanismCatalog(assets, task.pool)).evaluate(deck)
    for row in policy['metrics']:
        value = _quality_source(quality if row['path'][0] == 'quality' else evaluation, row['path']) if (quality if row['path'][0] == 'quality' else evaluation) else None
        known = type(value) in (int, float) and math.isfinite(value)
        passed = known and (value >= row['threshold'] if row['operator'] == 'ge' else value <= row['threshold'])
        metrics.append(dict(row, value=value, status='passed' if passed else 'failed' if known else 'unknown'))
        if not passed:
            reasons.append('quality_metric:' + '/'.join(row['path']) + (':failed' if known else ':unknown'))
    declared = policy['pass']
    if declared['mode'] == 'reference_ratio':
        ref = declared['reference']
        line = dict(kind='reference_ratio_pass_line', mode='reference_ratio',
            reference_id=ref['reference_id'], ratio=declared['minimum_reference_ratio'], status='unknown')
        if reference_quality is None:
            reasons.append('reference_evaluation_missing')
        elif reference_quality.get('deck_sha256') != ref['deck_sha256']:
            raise ContractError('reference evaluation does not bind the specified reference')
        else:
            reference_deck = DeckParts.from_dict(reference_quality['inventory'])
            _quality_binding(policy, reference_quality, reference_deck, comparisons)
            if reference_quality['task_sha256'] != task.sha256:
                raise ContractError('reference belongs to another original task')
            if not reference_validated:
                try:
                    assets.validate(task, reference_deck)
                except ContractError as error:
                    reasons.append('reference_invalid:' + str(error))
            if quality is not None:
                bounds = comparisons.delta(reference_quality, quality, declared['minimum_reference_ratio'])
                line.update(delta=bounds, reference_evaluation_id=reference_quality['evaluation_id'],
                    candidate_evaluation_id=quality['evaluation_id'])
                line['status'] = ('passed' if bounds['lower'] is not None and bounds['lower'] >= 0 else
                                  'failed' if bounds['upper'] is not None and bounds['upper'] < 0 else 'unknown')
                native_rules = getattr(assets, 'construction_rules', None)
                if native_rules is not None and 'native_rule_evidence' in quality and 'native_rule_evidence' in reference_quality:
                    native_rules.record_comparison(quality, reference_quality, bounds)
            if not reference_quality.get('complete'):
                reasons.append('reference_evaluation_incomplete')
            if any(r['status'] != 'satisfied' for r in reference_quality.get('hard_requirements', ())):
                reasons.append('reference_hard_requirement_unmet')
            if reference_quality.get('score', {}).get('value') is not None and reference_quality['score']['value'] <= 0:
                reasons.append('reference_score_nonpositive')
        metrics.append(line)
        if line['status'] != 'passed':
            reasons.append('quality_pass_line:reference_ratio:' + line['status'])
    gate = dict(version=FUNCTIONAL_GATE_VERSION, task_sha256=task.sha256, deck_sha256=digest(deck.to_dict()),
        candidate_version=candidate_version, status='passed' if not reasons else 'pending', policy=policy,
        metrics=metrics, reasons=reasons, inventory_dependencies=dependencies, quality_binding=binding, cb_result_used=False)
    gate['outcome'] = gate_outcome(gate)
    gate['evaluation_complete'] = bool(quality and quality['complete'] and (
        declared['mode'] != 'reference_ratio' or reference_quality and reference_quality['complete']))
    gate['static_completeness'] = {role: dict(complete=q['complete'], scope_complete=q['scope_complete'],
        unresolved=len(q['unknowns']), deferred=q['deferred'], partial=q['total']['partial_items'],
        hard_requirements=q['hard_requirements'], rule_evidence=sorted({row['rule'] for row in
            q.get('condition_applicability', ()) if row['status'] == 'inventory_present'}))
        for role, q in (('candidate', quality), ('reference', reference_quality)) if q is not None}
    return gate


def construction_gate(task, deck, assets, evaluation, *, policy=None, candidate_version=0, quality=None,
                      reference_quality=None, _comparisons=None, _reference_validated=False):
    policy = quality_policy(policy)
    if policy is None:
        return dict(version=FUNCTIONAL_GATE_VERSION, task_sha256=task.sha256, deck_sha256=digest(deck.to_dict()),
            candidate_version=candidate_version, status='pending', policy=None, metrics=[],
            reasons=['quality_policy_unconfigured'], quality_binding={'required':True,'present':False}, cb_result_used=False)
    from .construction_quality import EvaluationComparisons
    return _functional_gate(task, deck, assets, evaluation, policy, candidate_version, quality,
                            reference_quality, _comparisons or EvaluationComparisons(),
                            reference_validated=_reference_validated)


def record_reference_attempt(state, gate):
    """Count one completed comparison per optimizer iteration, never a retry."""
    if (gate.get('policy') != state['quality_policy'] or gate.get('version') != FUNCTIONAL_GATE_VERSION
            or gate.get('task_sha256') != state['task_sha256']
            or gate.get('candidate_version') != state['candidate_version']):
        raise ContractError('reference attempt belongs to another task, policy or candidate')
    if state['quality_policy']['pass']['mode'] != 'reference_ratio':
        state.pop('reference_feedback', None)
        return None
    failed = gate_outcome(gate) == 'failed'
    if (not failed and gate['status'] != 'passed') or gate.get('evaluation_complete') is False:
        return None
    policy_sha = digest(state['quality_policy'])
    feedback = dict(state.get('reference_feedback') or dict(policy_sha256=policy_sha,
        last_iteration=0, consecutive_below_reference=0, hint_stage=None))
    if feedback['policy_sha256'] != policy_sha:
        raise ContractError('reference attempt counter requires policy revision')
    if state['iteration'] <= feedback['last_iteration']:
        return None
    feedback['last_iteration'] = state['iteration']
    feedback['consecutive_below_reference'] = feedback['consecutive_below_reference'] + 1 if failed else 0
    count = feedback['consecutive_below_reference']
    feedback['hint_stage'] = None if count < 2 else ('main_axis' if count == 2 else 'secondary_axes' if count == 3 else 'generic')
    state['reference_feedback'] = feedback
    messages = {
        'main_axis':'连续两次完成构筑检查仍未通过。先检查主轴的启动与核心处理，补足必要对象、代价和素材。',
        'secondary_axes':'继续检查副轴能否补足主轴所缺的功能，并确认代价、素材和通常召唤次数不会互相争用。',
        'generic':'检查泛用配置对当前目标的实际作用、重复投入与换备配合，撤去失去配套的投入。',
    }
    stage = feedback['hint_stage']
    return dict(stage=stage, message=messages[stage]) if stage else None


def record_basic_cb_attempt(state, inference):
    """Two normal, completed route failures request another optimizer round."""
    if (inference.get('task_sha256') != state['task_sha256'] or
            inference.get('subject_deck_sha256') != state['candidate']['deck_sha256']):
        raise ContractError('CB attempt belongs to another construction candidate')
    if inference.get('normal_completion') is not True:
        return False
    previous = state.get('basic_cb_feedback') or {}
    count = previous.get('consecutive_failures',0) if previous.get('candidate_version') == state['candidate_version'] else 0
    success = inference.get('status') == 'routes_inferred' and bool(inference.get('routes'))
    if success:
        count = 0
    elif inference.get('failure_count_eligible') is True and inference.get('status') == 'no_route_found':
        count += 1
    else:
        return False
    state['basic_cb_feedback'] = dict(candidate_version=state['candidate_version'],consecutive_failures=count)
    return count >= 2


def restore_progress(session, value, assets, *, policy=None, _comparisons=None):
    if value is None:
        session.construction_progress = None
        return
    state = deepcopy(value)
    if (state.get('schema_version') not in (2, 3) or state.get('task_sha256') != session.task.sha256
            or state.get('logic_sha256') != (session.logic.sha256 if session.logic else None)
            or state.get('status') not in ('optimizing', 'suspended', 'passed')
            or type(state.get('iteration')) is not int or state['iteration'] < 0
            or type(state.get('candidate_version')) is not int or state['candidate_version'] < 1):
        raise ContractError('construction continuation differs from original task or logic')
    legacy = state['schema_version'] == 2
    if not legacy:
        quality_policy(state.get('quality_policy'))
        feedback = state.get('reference_feedback')
        if feedback is not None and (not isinstance(feedback, dict)
                or set(feedback) != {'policy_sha256', 'last_iteration', 'consecutive_below_reference', 'hint_stage'}
                or feedback['policy_sha256'] != digest(state['quality_policy'])
                or type(feedback['last_iteration']) is not int or not 0 <= feedback['last_iteration'] <= state['iteration']
                or type(feedback['consecutive_below_reference']) is not int or feedback['consecutive_below_reference'] < 0
                or feedback['consecutive_below_reference'] > feedback['last_iteration']
                or feedback['hint_stage'] != (None if feedback['consecutive_below_reference'] < 2 else
                    'main_axis' if feedback['consecutive_below_reference'] == 2 else
                    'secondary_axes' if feedback['consecutive_below_reference'] == 3 else 'generic')):
            raise ContractError('saved reference feedback differs from its completed comparisons')
    from .construction_quality import (
        SUPPORTED_FUNCTIONAL_QUALITY_VERSIONS, EvaluationComparisons, restore_comparison_progress,
    )
    comparisons = _comparisons or EvaluationComparisons()
    expected_quality_version = ((state.get('quality_policy') or {}).get('quality') or {}).get('evaluator_version')
    functional = expected_quality_version in SUPPORTED_FUNCTIONAL_QUALITY_VERSIONS
    initial_admission = state.get('initial_admission')
    if initial_admission is not None:
        init_gate = initial_admission.get('gate') if isinstance(initial_admission, dict) else None
        if (not isinstance(initial_admission, dict)
                or initial_admission.get('version') != FUNCTIONAL_GATE_VERSION
                or initial_admission.get('task_sha256') != session.task.sha256
                or not isinstance(init_gate, dict) or init_gate.get('status') != 'passed'
                or init_gate.get('task_sha256') != session.task.sha256
                or init_gate.get('deck_sha256') != initial_admission.get('deck_sha256')):
            raise ContractError('saved initial admission differs from original task or gate')
    feedback_mode = state.get('admission_mode') == 'feedback_revision'
    if feedback_mode:
        if not is_initial_admitted(state, session.task.sha256):
            raise ContractError('feedback revision requires a prior initial admission')
        hc = state.get('feedback_hard_check')
        if (not isinstance(hc, dict) or hc.get('version') != FEEDBACK_HARD_CHECK_VERSION
                or hc.get('task_sha256') != session.task.sha256
                or hc.get('static_scoring_calls') != 0):
            raise ContractError('saved feedback revision lost its hard check binding')
    deck = DeckParts.from_dict(state['candidate']['deck'])
    (assets.validate_skeleton if state['candidate'].get('layer_evaluation') is None else assets.validate)(session.task, deck)
    if state['candidate'].get('deck_sha256') != digest(deck.to_dict()):
        raise ContractError('construction continuation candidate binding differs')
    handoffs = state.get('handoffs', [])
    first = handoffs[0] if handoffs else {}
    if first.get('role') == 'build_optimizer':
        draft = goal_effect_draft(session)
        if (draft is None or first.get('input_draft_sha256') != draft['logic_sha256']
                or first.get('candidate_version') != 1 or first.get('input_deck_sha256') is not None
                or state['iteration'] == 0 and draft['logic_sha256'] != session.logic.sha256):
            raise ContractError('construction continuation lost its optimizer input draft')
    if (first.get('role') not in ('build_goal', 'build_optimizer')
            or any(r['role'] != 'build_optimizer' for r in handoffs[1:])
            or any(b['input_deck_sha256'] != a['output_deck_sha256'] for a,b in zip(handoffs,handoffs[1:]))
            or handoffs[-1]['output_deck_sha256'] != digest(deck.to_dict())
            or handoffs[-1]['candidate_version'] != state['candidate_version']):
        raise ContractError('construction continuation lost actual role handoff ancestry')
    compact_completed_progress(state)
    if legacy:
        state.pop('reference_feedback', None)
        old_policy = state.get('quality_policy')
        state['legacy_quality_policy'] = deepcopy(old_policy)
        state.update(schema_version=3,quality_policy=quality_policy(policy),status='optimizing',gate=None,
            reference_evaluation=None,stop_reason='legacy_quality_reevaluation_required',
            quality_migration=dict(from_schema=2,target='functional_log2',scalar_scores_reused=False,
                slot_statuses_inferred=False,rebind_paths=[]))
        rows = [('candidate',state['candidate']),*((f'retained_candidates.{i}',r)
            for i,r in enumerate(state.get('retained_candidates',())))]
        if state.get('pending_quality'):
            pending = state['pending_quality']
            rows.extend((f'pending_quality.evaluations.{k}',r) for k,r in pending.get('evaluations',{}).items())
            pending['policy_sha256'] = digest(state['quality_policy'])
        for path,row in rows:
            if row.get('quality_evaluation') is not None:
                row['stale_quality_evaluation'] = row.pop('quality_evaluation')
                for field in ('slot_ledger','losses','loss_records'):
                    if field in row['stale_quality_evaluation']:
                        state['quality_migration']['rebind_paths'].append(path+'.stale_quality_evaluation.'+field)
            row.update(evaluation_status='stale')
            row.pop('construction_gate',None)
            row.pop('quality_comparisons',None)
        expected_quality_version = ((state.get('quality_policy') or {}).get('quality') or {}).get('evaluator_version')
        functional = state['quality_policy'] is not None
    if functional or state['schema_version'] == 3:
        policy_sha = digest(state.get('quality_policy'))
        from .construction_layer_flow import (functional_asset_version, reference_asset_binding,
            NORMALIZATION_VERSION, REFERENCE_BINDING_VERSION)
        from .effect_mechanisms import MechanismCatalog
        catalog = MechanismCatalog(assets, session.task.pool)
        asset_version = functional_asset_version(catalog)
        native_rules = getattr(assets, 'construction_rules', None)

        def frontier(inventory, role):
            return (native_rules.frontier_binding(session.task, DeckParts.from_dict(inventory), role,
                    state['quality_policy']) if native_rules is not None else None)

        pending = state.get('pending_quality')
        stage = state.get('pending_reference')
        selection_rows = []
        if stage is not None:
            if isinstance(stage, dict) and stage.get('version') is None and all(str(key).isdecimal() for key in stage):
                # The older format kept the candidate batch but lacked a saved selection.
                state['pending_reference'] = stage = None
            elif (not isinstance(stage, dict) or stage.get('version') != REFERENCE_STAGE_VERSION
                    or pending is not None
                    or ((state.get('quality_policy') or {}).get('pass') or {}).get('mode') != 'reference_ratio'):
                raise ContractError('saved reference phase binding differs')
        if stage is not None:
            phase = state.get('pending_phase') or {}
            selection = phase.get('stage_3') or {}
            pending = stage.get('candidate_batch')
            portfolio = selection.get('portfolio') or ()
            selected = next((row for row in portfolio if row['deck'] == selection.get('best_deck')), None)
            if (phase.get('role') != 'build_optimizer' or phase.get('optimization_iteration') != state['iteration'] + 1
                    or phase.get('input_candidate_version') != state['candidate_version']
                    or phase.get('input_deck') != state['candidate']['deck']
                    or selection.get('status') != 'concrete_candidate_cb_pending' or not selection.get('selection_complete')
                    or selected is None or selected.get('quality_evaluation') != selection.get('quality_evaluation')
                    or not isinstance(pending, dict) or pending.get('evaluations') or pending.get('calculation_progress')):
                raise ContractError('saved reference phase lost its completed candidate selection')
            selection_rows = [*portfolio, *selection.get('learning_candidates', ())]
        if pending is not None:
            if (pending.get('version') != 'functional-candidate-batch-v1'
                    or pending.get('task_sha256') != session.task.sha256
                    or pending.get('logic_sha256') != session.logic.sha256
                    or pending.get('policy_sha256') != digest(state['quality_policy'])
                    or sorted(pending['order']) != list(range(len(pending['candidates'])))):
                raise ContractError('pending quality batch binding or candidate order differs')
            if stage is None and pending.get('comparison_progress') is not None:
                restore_comparison_progress(pending['comparison_progress'])
            for row in pending['candidates']:
                assets.validate(session.task, DeckParts.from_dict(row['deck']))
            for key,work in list(pending.get('calculation_progress',{}).items()):
                if (work.get('normalization_version')!=NORMALIZATION_VERSION
                        or work.get('asset_version')!=asset_version
                        or work.get('native_frontier') != frontier(pending['candidates'][int(key)]['deck'], 'candidate')):
                    del pending['calculation_progress'][key]
            for key, row in pending['evaluations'].items():
                if row['layer_evaluation']['axis']['inventory'] != pending['candidates'][int(key)]['deck']:
                    raise ContractError('pending evaluation belongs to another candidate')
        saved = [(row, False) for row in (state['candidate'], *state.get('retained_candidates', []))]
        if pending is not None:
            saved.extend((row, False) for row in pending['evaluations'].values())
        saved.extend((row, True) for row in selection_rows)
        stale = False
        stale_selection = False
        for row, selected in saved:
            quality = row.get('quality_evaluation')
            if quality is None:
                if feedback_mode and row is state['candidate']:
                    continue
                if row.get('layer_evaluation') is not None:
                    row['evaluation_status'] = 'stale'
                    stale = True
                    stale_selection |= selected
                continue
            inventory = row.get('deck') or row['layer_evaluation']['axis']['inventory']
            if quality.get('deck_sha256') != digest(inventory) or quality.get('task_sha256') != session.task.sha256:
                raise ContractError('saved quality belongs to another task/candidate')
            if quality.get('version') in SUPPORTED_FUNCTIONAL_QUALITY_VERSIONS:
                comparisons.bind(quality)
            outdated = (quality.get('version') != expected_quality_version
                or quality.get('normalization_version') != NORMALIZATION_VERSION
                or quality.get('function_dictionary_version') != (state.get('quality_policy') or {}).get('quality',{}).get('function_dictionary_version')
                or quality.get('asset_version') != asset_version
                or quality.get('native_rule_evidence', {}).get('frontier') != frontier(inventory, 'candidate')
                or quality.get('policy_sha256') != policy_sha)
            if not outdated and getattr(catalog.assets, "rule_authority", None) != "locked_period_core":
                outdated = any(e['record']['text_sha256'] != catalog.card(int(key.split(':')[1])).text_sha256
                    for key, detail in quality.get('coverage_details', {}).items() for e in detail.get('effects', ()))
            if outdated:
                row['stale_quality_evaluation'] = row.pop('quality_evaluation')
                row['evaluation_status'] = 'stale'
                stale = True
                stale_selection |= selected
            elif row.get('layer_evaluation') is not None and quality['logic_sha256'] != digest(row['layer_evaluation']['axis'].get('logic')):
                raise ContractError('saved quality logic binding differs')
        if pending is not None:
            pending['evaluations'] = {k: r for k, r in pending['evaluations'].items() if r.get('quality_evaluation')}
            pending['pending_indices'] = [i for i in pending['order'] if str(i) not in pending['evaluations']]
        if stale_selection:
            _reopen_reference_batch(state)
        elif stage is not None and pending.get('comparison_progress') is not None:
            from itertools import combinations
            order, pairs = restore_comparison_progress(pending['comparison_progress'])
            expected_order = [[i, selection['candidate_trace']['candidates'][i]['quality_evaluation_id']]
                              for i in pending['order'] if str(i) not in pending['binding_errors']
                              and i not in pending['binding_errors']]
            if order != expected_order or len(pairs) != len(order) * (len(order) - 1) // 2:
                raise ContractError('saved reference phase lost its completed comparisons')
            qualities = {row['quality_evaluation']['evaluation_id']: row['quality_evaluation'] for row in selection_rows}
            for ((_, before), (_, after)), pair in zip(combinations(order, 2), pairs):
                if before in qualities and after in qualities:
                    comparisons.restore_pair(qualities[before], qualities[after], pair)
        reference = state.get('reference_evaluation')
        if reference is not None:
            descriptor = ((state.get('quality_policy') or {}).get('pass') or {}).get('reference')
            if (reference.get('task_sha256') != session.task.sha256 or descriptor is None
                    or reference.get('deck_sha256') != descriptor['deck_sha256']):
                raise ContractError('saved reference belongs to another task or specified listing')
            if reference.get('version') in SUPPORTED_FUNCTIONAL_QUALITY_VERSIONS:
                comparisons.bind(reference)
            binding = state.get('reference_binding')
            if (reference.get('version') != expected_quality_version or reference.get('asset_version') != asset_version
                    or reference.get('normalization_version') != NORMALIZATION_VERSION
                    or reference.get('native_rule_evidence', {}).get('frontier') != frontier(reference['inventory'], 'reference')
                    or reference.get('function_dictionary_version') != state['quality_policy']['quality']['function_dictionary_version']
                    or reference.get('policy_sha256') != policy_sha
                    or reference.get('logic_sha256') != digest(None)
                    or not isinstance(binding, dict) or binding.get('version') != REFERENCE_BINDING_VERSION
                    or binding.get('assets') != reference_asset_binding(catalog, DeckParts.from_dict(reference['inventory']))):
                invalidate_reference_evaluation(state)
                stale = True
        if functional and state.get('gate') and state['gate'].get('version') != FUNCTIONAL_GATE_VERSION:
            stale = True
        if stale:
            state.pop('reference_feedback', None)
            state.update(status='optimizing', gate=None, stop_reason='quality_reevaluation_required')
        state['schema_version'] = 3
    if state['status'] == 'passed':
        if state.get('admission_mode') == 'feedback_revision':
            hc = state.get('feedback_hard_check') or {}
            if (hc.get('version') != FEEDBACK_HARD_CHECK_VERSION or hc.get('passed') is not True
                    or hc.get('deck_sha256') != digest(deck.to_dict())
                    or hc.get('task_sha256') != session.task.sha256
                    or hc.get('candidate_version') != state['candidate_version']
                    or hc.get('static_scoring_calls') != 0):
                raise ContractError('feedback revision pass does not bind the saved hard check')
        else:
            gate=state.get('gate') or {}
            if (gate.get('version') != (FUNCTIONAL_GATE_VERSION if functional else GATE_VERSION) or gate.get('status') != 'passed'
                    or gate.get('deck_sha256') != digest(deck.to_dict()) or gate.get('task_sha256') != session.task.sha256
                    or gate.get('candidate_version') != state['candidate_version'] or gate.get('policy') != state['quality_policy']):
                raise ContractError('construction pass does not bind the saved candidate')
            binding = gate.get('quality_binding') or {}
            if binding.get('required'):
                # A saved pass keeps the exact quality record it was earned with.
                if not binding.get('present'):
                    raise ContractError('saved construction pass lost its quality evaluation')
                current = _quality_binding(state['quality_policy'], state['candidate'].get('quality_evaluation'), deck, comparisons)
                if (functional and current != binding or current.get('value') != binding.get('value')
                        or current.get('complete') != binding.get('complete')):
                    raise ContractError('construction pass quality record changed after it was earned')
            if functional and state['quality_policy']['pass']['mode'] == 'reference_ratio':
                reference = state.get('reference_evaluation') or {}
                line = next((m for m in gate['metrics'] if m.get('kind') == 'reference_ratio_pass_line'), {})
                if not reference or line.get('reference_evaluation_id') != reference.get('evaluation_id'):
                    raise ContractError('saved construction pass lost its fixed reference evaluation')
    session.construction_progress = state


def revise_quality_policy(session, policy):
    """Explicit host revision, preserving inventories, skeleton and cursors."""
    policy = quality_policy(policy)
    if policy is None or session.construction_progress is None:
        raise ContractError('policy revision requires a configured in-progress construction')
    state = deepcopy(session.construction_progress)
    old = state.get('quality_policy')
    if old == policy:
        return
    state.setdefault('policy_revisions', []).append(dict(before=digest(old), after=digest(policy)))
    invalidate_reference_evaluation(state)
    _reopen_reference_batch(state)
    state.pop('initial_admission', None)
    state.pop('admission_mode', None)
    state.pop('feedback_hard_check', None)
    state.pop('post_admission_feedback', None)
    state.update(quality_policy=policy, status='optimizing', gate=None,
                 schema_version=3, stop_reason='quality_policy_revised')
    for row in [state['candidate'], *state.get('retained_candidates', [])]:
        if row.get('quality_evaluation') is not None:
            row['stale_quality_evaluation'] = row.pop('quality_evaluation')
        row['evaluation_status'] = 'stale'
        row.pop('quality_comparisons', None)
        row.pop('construction_gate', None)
    if state.get('pending_quality'):
        state['pending_quality'].update(policy_sha256=digest(policy), evaluations={},
            calculation_progress={}, pending_indices=list(state['pending_quality']['order']), evaluation_cursor=0,
            comparison_progress=None)
    session.construction_progress = state


def record_optimization_feedback(session, value):
    required = {'feedback_id', 'source', 'task_sha256', 'candidate_sha256', 'issue'}
    optional = {'suggested_package', 'revised_deck', 'trigger_kind'}
    if (not isinstance(value, dict) or required - value.keys()
            or set(value) - required - optional
            or value['source'] not in ('coordinator', 'duel', 'external_ai', 'basic_cb')
            or value['task_sha256'] != session.task.sha256
            or any(not isinstance(value[k], str) or not value[k].strip() for k in required)
            or len(value['candidate_sha256']) != 64):
        raise ContractError('optimization feedback requires source, task, candidate and issue')
    trigger_kind = value.get('trigger_kind')
    if trigger_kind is not None and trigger_kind not in ('basic_cb', 'duel', 'coordinator', 'external_ai'):
        raise ContractError('unsupported optimization feedback trigger kind')
    if 'revised_deck' in value and value['revised_deck'] is not None and not isinstance(value['revised_deck'], dict):
        raise ContractError('revised feedback deck must be a deck mapping')
    package = value.get('suggested_package')
    if package is not None:
        deck = DeckParts.from_dict(package)
        if len(deck.main + deck.extra + deck.side) > 6 or not set(deck.main + deck.extra + deck.side) <= set(session.task.pool):
            raise ContractError('feedback package must be bounded by the original task pool')
    prior = next((r for r in session.optimization_feedback if r['input']['feedback_id'] == value['feedback_id']), None)
    if prior is not None:
        if prior['input'] != value:
            raise ContractError('optimization feedback identity already bound')
        return
    session.optimization_feedback.append({'input': deepcopy(value), 'status': 'pending', 'consumed_iteration': None})


def feedback_for_iteration(session, deck, iteration):
    messages, packages, receipts = [], [], []
    for row in session.optimization_feedback:
        if row['status'] != 'pending':
            continue
        value = row['input']
        if value['candidate_sha256'] != digest(deck.to_dict()):
            row.update(status='stale_candidate', reason='feedback targets a different inventory')
            continue
        messages.append({'source': value['source'], 'message': value['issue'][:1024]})
        if value.get('suggested_package') is not None:
            packages.append(dict(group_id=value['feedback_id'], zones=value['suggested_package'], source=value['source']))
        row.update(status='consumed_pending_assessment', consumed_iteration=iteration)
        receipts.append(row)
    return messages, packages, receipts


def finish_feedback(receipts, candidate):
    for row in receipts:
        package = row['input'].get('suggested_package')
        revised = row['input'].get('revised_deck')
        if candidate is None:
            row.update(status='not_adopted', reason='no valid candidate in this slice')
        elif revised is not None:
            adopted = digest(candidate.to_dict()) == digest(DeckParts.from_dict(revised).to_dict())
            row.update(status='adopted' if adopted else 'not_adopted',
                reason='revised feedback inventory adopted' if adopted else 'optimizer selected another valid inventory')
        elif package is None:
            row.update(status='reviewed_unverified', reason='issue entered optimizer context; resolution needs evidence')
        else:
            from collections import Counter
            adopted = all(not (Counter(package[z]) - Counter(getattr(candidate, z))) for z in package)
            row.update(status='adopted' if adopted else 'not_adopted',
                reason='suggested inventory present' if adopted else 'optimizer selected another valid inventory')
        row['output_candidate_sha256'] = digest(candidate.to_dict()) if candidate else None
