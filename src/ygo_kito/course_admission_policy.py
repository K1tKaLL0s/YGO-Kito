"""Host-owned prospective construction scores and conditional-CB signals.

Private reviews, calibration manifests, audits and hint counters stay outside
the learner source/data tree. Admission is a pure read; only completed inference
and construction callbacks advance their separate counters.
"""
from copy import deepcopy
from dataclasses import asdict, is_dataclass, replace
from hashlib import sha256
import json
from pathlib import Path

from .build_contracts import digest
from .effect_mechanisms import MechanismCatalog, SEMANTIC_VERSION
from .reference_hint_templates import templates_for_period
from .reference_hints import ReferenceHintTracker
from .reference_scoring import (PEARL_PRIORS, Policy, Requirement, VERSION as RUBRIC_VERSION,
                                public_result, score_construction)
from .reference_scoring_adapter import (propose_functional_units, read_semantic_registry,
                                        review_deck)
from .reference_scoring_feedback import record_scoring_feedback
from .validation import ContractError


POLICY_EPOCH = 'prospective-construction-admission-20-50-v1'
HISTORICAL_PERIODS = ('2022-07', '2022-10')
CONTEXT_VERSION = 'actual-inventory-bound-functional-relations-v3-active-scoring-evidence'


def _deck_key(deck):
    raw = deck.to_dict() if hasattr(deck, 'to_dict') else deck
    return digest({z: sorted(raw.get(z, ())) for z in ('main', 'extra', 'side')})


def candidate_functional_units(deck, catalog, *, theme, period_id):
    """Bind proposed Pearl relations to actual main/extra mechanism witnesses.

    Recognized material compatibility and the proposed opening are bounded
    static evidence, never an executed route. Theme-level presence templates
    alone receive no relation credit. Other goals need their own reviewed graph.
    """
    if period_id not in HISTORICAL_PERIODS or theme != 'pearl_grave_fusion':
        return ()
    templates = propose_functional_units((), theme=theme)
    main_template = next(u for u in templates if u.category == 'main_axis')
    units = []
    pool = tuple(dict.fromkeys(deck.main + deck.extra))
    targets = tuple(c for c in dict.fromkeys(deck.extra)
                    if catalog.assets.rows[c]['type'] & 0x40)
    for goal in (catalog.fusion_goals(pool, targets, limit=8) if targets else ()):
        target = goal.get('card_id')
        starters = tuple(dict.fromkeys(goal.get('starting_conditions', {}).get('requires_opening_hand', ())))
        assessments = goal.get('fusion_witness', {}).get('effect_assessments', ())
        enablers = tuple(dict.fromkeys(a['card_id'] for a in assessments
            if a.get('status') == 'satisfied' and a.get('source') == SEMANTIC_VERSION))
        if (target not in targets or not starters or not enablers or
                any(c not in deck.main for c in starters + enablers)):
            continue
        identity = digest({'semantic_version': SEMANTIC_VERSION, 'goal': goal})
        units.append(replace(main_template, key='actual-grave-fusion-' + identity[:24],
            requirements=(
                Requirement(('mill', 'targeted_send'), ('main',),
                    tuple('main:' + str(c) for c in starters), len(starters)),
                Requirement(('grave_fusion',), ('main',),
                    tuple('main:' + str(c) for c in enablers), len(enablers)),
                Requirement(('@present',), ('extra',), ('extra:' + str(target),))),
            relation_status='proposed',
            conditions=main_template.conditions + ('actual candidate material/opening witness: ' + identity,),
            risks=main_template.risks + ('static proposal; successful native CB is checked independently',)))
    if not units:
        units.append(replace(main_template, relation_status='unknown',
            risks=main_template.risks + ('no compatible actual candidate fusion witness',)))
    # No current graph witness supports these additional relations. Co-presence
    # of grave loading, interaction or recovery blocks cannot supply that edge.
    units.extend(replace(u, relation_status='unknown',
        risks=u.risks + ('actual candidate relationship not reviewed',))
        for u in templates if u.category != 'main_axis')
    return tuple(units)


class ActualCandidateContext:
    """Conservative structural review of THIS inventory, never reference factors.

    The reference registry supplies text-bound functional facts. Its numerical
    feasibility/resource/conflict assumptions are discarded. This bounded
    reviewer credits only catalog-recognized, cost/target/resource independent
    effects; unresolved current conditions remain unknown. Richer trusted host
    reviewers can be injected without changing the learner-facing interface.
    """
    def __init__(self, catalog):
        self.catalog = catalog

    def __call__(self, row, block, deck, rows):
        profile = self.catalog.card(row['id'])
        matching = [e for e in profile.effects if e.text and
                    (e.text in block.quote or block.quote in e.text)]
        effect = matching[0] if len(matching) == 1 else None
        knowledge = {k: 'unknown' for k in ('conditions', 'costs', 'limits', 'resources', 'conflicts')}
        if effect is not None:
            knowledge.update(
                conditions='known' if effect.conditions_known else 'unknown',
                costs='known' if not effect.costs and effect.knowledge.get('costs') in
                    ('not_observed_in_recognized_activation', 'not_applicable') else 'unknown',
                limits='known' if effect.count_limits and all(
                    v.get('status') == 'known' for v in effect.count_limits) else 'unknown',
                resources='known' if not effect.targets and not block.resources and
                    effect.knowledge.get('targets') == 'not_observed_in_recognized_activation' else 'unknown',
                conflicts='known' if not effect.restrictions and
                    effect.knowledge.get('restrictions') != 'unknown' else 'unknown')
        # Actual listing is necessary for any deck/hand resource claim. We do
        # not substitute a reference's target distribution or starting hand.
        if block.kind == 'mill' and effect is not None:
            mills = [op for op in effect.observed_operations if op['kind'] == 'mill'
                     and op.get('owner') == 'self' and op.get('from_zones') == ('deck',)]
            if (mills and not effect.targets and
                    effect.knowledge.get('targets') == 'not_observed_in_recognized_activation' and
                    all(type(op.get('quantity')) is int for op in mills)):
                amount = max(op['quantity'] for op in mills)
                if type(amount) is int and amount <= max(0, len(deck.get('main', ())) - 5):
                    knowledge['resources'] = 'known'
        status = 'reviewed' if all(v != 'unknown' for v in knowledge.values()) else 'unknown'
        return replace(block, status=status, feasibility=1., cost_factor=1.,
            count_factor=.9 if effect is not None and effect.count_limits else 1.,
            resource_factor=1., conflict_factor=1., knowledge=knowledge,
            resources=('actual candidate inventory reviewed; unresolved requirements stay unknown',),
            conflicts=() if knowledge['conflicts'] == 'known' else ('current candidate conflicts unreviewed',))


class CourseAdmissionPolicy:
    """Persisted host provider. Calls do not infer, score, count or train."""
    def __init__(self, state_path, *, private_root, period_id, theme=None, priors=None,
                 contextualize_factory=None, policy_epoch=POLICY_EPOCH, logical_course_id=None):
        self.path = Path(state_path)
        self.private_root = Path(private_root)
        self.period_id, self.theme, self.priors = period_id, theme, deepcopy(priors)
        self.contextualize_factory = contextualize_factory or ActualCandidateContext
        self.policy_epoch = policy_epoch
        self.logical_course_id = logical_course_id
        if period_id in HISTORICAL_PERIODS and theme != 'pearl_grave_fusion':
            raise ContractError('historical reference requires the explicitly selected Pearl goal')
        self.registry = {}
        self.manifest = None
        if period_id in HISTORICAL_PERIODS:
            self.registry = read_semantic_registry(json.loads(
                (self.private_root / 'reviewed_semantics.json').read_text(encoding='utf-8-sig')))
            self.manifest = json.loads((self.private_root / 'calibration-manifests.json').read_text(
                encoding='utf-8-sig'))[period_id]
            if (self.manifest['reference_period_id'] != period_id or
                    self.manifest['theme'] != theme or self.manifest['reference_score'] != 70):
                raise ContractError('private reference calibration period/theme mismatch')
        binding = {'policy_epoch': policy_epoch, 'period_id': period_id, 'theme': theme,
                   'logical_course_id': logical_course_id,
                   'priors_sha256': digest(priors) if priors else None,
                   'reference_scope': None if self.manifest is None else self.manifest['scope'],
                   'private_calibration_sha256': None if self.manifest is None else digest(self.manifest),
                   'semantic_review_sha256': digest(self.registry),
                   'mechanism_semantic_version': SEMANTIC_VERSION,
                   'candidate_context_version': CONTEXT_VERSION, 'rubric_version': RUBRIC_VERSION}
        if self.path.exists():
            self.value = json.loads(self.path.read_text(encoding='utf-8'))
            if self.value.get('binding') != binding:
                raise ContractError('admission policy changed; preserve its old epoch explicitly')
        else:
            self.value = {'kind': 'prospective-course-admission-v1', 'binding': binding,
                'construction_evaluations': {}, 'evaluation_ids': {}, 'cb_events': [],
                'cb_reviews': [], 'hint_state': None,
                'legacy_counter_imported': False, 'retrospective_unknowns_counted': False}
        self.tracker = None
        if period_id in HISTORICAL_PERIODS:
            self.tracker = (ReferenceHintTracker.from_dict(self.value['hint_state'])
                if self.value['hint_state'] is not None else
                ReferenceHintTracker(templates=templates_for_period(period_id)))

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.tracker is not None:
            self.value['hint_state'] = self.tracker.to_dict()
        temp = self.path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self.value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(self.path)

    def _assert_saved_state(self):
        if not self.path.is_file():
            raise ContractError('private admission state must be saved before checkpoint reference')
        data = self.path.read_bytes()
        try:
            saved = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise ContractError('private admission state is unreadable; preserve its saved boundary') from error
        if saved != self.value:
            raise ContractError('private admission state differs from its bound in-memory ledger')
        return data

    def checkpoint_descriptor(self):
        """A public checkpoint reference; contains no evaluator resources."""
        data = self._assert_saved_state()
        return {'kind': 'private-course-admission-ref-v1',
            'logical_course_id': self.logical_course_id, 'policy_epoch': self.policy_epoch,
            'binding_sha256': digest(self.value['binding']),
            'state_sha256': sha256(data).hexdigest()}

    def validate_checkpoint_descriptor(self, descriptor):
        if descriptor != self.checkpoint_descriptor():
            raise ContractError('checkpoint private admission reference differs; preserve both boundaries')

    def _identity(self, task, deck):
        return {'task_sha256': task.sha256, 'deck_sha256': digest(deck.to_dict())}

    def _scope_key(self, task, deck):
        return digest({'task': task.sha256, 'deck_multiset': _deck_key(deck), 'period': self.period_id})

    def _task_period(self, task, assets):
        if getattr(assets, 'period_id', self.period_id) != self.period_id:
            raise ContractError('admission asset period differs from its configured policy')
        environment = getattr(assets, 'environment', None)
        if environment is not None and task.environment != environment:
            raise ContractError('admission task environment differs from actual scoring assets')

    def consume_cb_signal(self, signal):
        row = asdict(signal) if is_dataclass(signal) else deepcopy(signal)
        required = {'attempt_id', 'task_sha256', 'deck_sha256', 'success', 'failure_count_eligible', 'reason'}
        if (not isinstance(row, dict) or set(row) != required or
                any(not isinstance(row[k], str) or not row[k] for k in
                    ('attempt_id', 'task_sha256', 'deck_sha256', 'reason')) or
                type(row['success']) is not bool or
                (row['failure_count_eligible'] is not None and type(row['failure_count_eligible']) is not bool)):
            raise ContractError('invalid completed conditional CB signal')
        previous = next((v for v in self.value['cb_events'] if v['attempt_id'] == row['attempt_id']), None)
        if previous is not None:
            if previous != row: raise ContractError('CB attempt ID already bound to another event')
            return
        # Not-run/random-start/guard events cannot change failure streaks.
        if not row['success'] and row['failure_count_eligible'] is not True:
            return
        self.value['cb_events'].append(row)
        self._save()

    def _cb_trigger(self, task):
        events = [r for r in self.value['cb_events'] if r['task_sha256'] == task.sha256]
        reviewed = {r['through_attempt_id'] for r in self.value['cb_reviews']
                    if r['task_sha256'] == task.sha256}
        last_review = max((i for i, r in enumerate(events) if r['attempt_id'] in reviewed), default=-1)
        streak = 0
        trigger = None
        for i, row in enumerate(events):
            if i <= last_review:
                continue
            streak = 0 if row['success'] else streak + 1
            if streak >= 2 and not row['success']:
                trigger = row['attempt_id']
        return trigger

    def review_completed(self, *, task, deck, cycle_id, through_attempt_id=None):
        """Consume only the trigger known BEFORE this completed construction."""
        if through_attempt_id is None: return
        key = self._scope_key(task, deck)
        if not any(r['cycle_id'] == cycle_id for r in self.value['construction_evaluations'].get(key, ())):
            raise ContractError('CB optimization acknowledgement needs its completed construction evaluation')
        if not any(r['attempt_id'] == through_attempt_id and r['task_sha256'] == task.sha256
                   for r in self.value['cb_events']):
            raise ContractError('unknown conditional CB trigger acknowledgement')
        row = {'task_sha256': task.sha256, 'cycle_id': cycle_id, 'through_attempt_id': through_attempt_id}
        if row not in self.value['cb_reviews']:
            self.value['cb_reviews'].append(row); self._save()

    def record_completed_construction(self, *, task, deck, assets, basic_cb, cycle_id, evaluation_id=None):
        """Score one actual completed candidate once, independently of guards."""
        self._task_period(task, assets)
        if not isinstance(cycle_id, str) or not cycle_id.strip():
            raise ContractError('completed construction requires an explicit cycle identity')
        key = self._scope_key(task, deck)
        evaluation_id = evaluation_id or 'construction-score-' + digest({'scope': key, 'cycle': cycle_id})
        if (not isinstance(evaluation_id, str) or not evaluation_id or
                Path(evaluation_id).name != evaluation_id or
                any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in evaluation_id)):
            raise ContractError('evaluation ID must be a plain host identifier')
        identity = {**self._identity(task, deck), 'deck_multiset_sha256': _deck_key(deck),
            'cycle_id': cycle_id, 'evaluation_id': evaluation_id, 'period_id': self.period_id}
        old = self.value['evaluation_ids'].get(evaluation_id)
        if old is not None:
            if old != identity: raise ContractError('construction evaluation ID already bound')
            return deepcopy(next(v['public_feedback'] for v in self.value['construction_evaluations'][key]
                                 if v['evaluation_id'] == evaluation_id))
        same = next((v for v in self.value['construction_evaluations'].get(key, ())
                     if v['cycle_id'] == cycle_id), None)
        if same is not None:
            self.value['evaluation_ids'][evaluation_id] = identity; self._save()
            return deepcopy(same['public_feedback'])
        # A new autonomous goal has no historical anchor or reference hints.
        if self.period_id not in HISTORICAL_PERIODS and (not self.theme or not self.priors):
            feedback = {'reference_comparison_applicable': False,
                'construction_strength_status': 'unknown', 'force_optimization': False,
                'score': None, 'hint': None}
            audit = {'evaluation_context': {'goal_id': task.sha256, 'period_id': self.period_id},
                'reason': 'autonomous_goal_has_no_historical_reference_anchor', 'strength_status': 'unknown'}
        else:
            if not self.priors: raise ContractError('explicit goal-conditioned scoring priors required')
            catalog = MechanismCatalog(assets, tuple(dict.fromkeys(deck.main + deck.extra + deck.side)))
            reviews = review_deck(deck.to_dict(), assets.rows, semantic_registry=self.registry,
                catalog=catalog, contextualize=self.contextualize_factory(catalog))
            units = candidate_functional_units(deck, catalog, theme=self.theme, period_id=self.period_id)
            calibration_binding = {'period_id': self.period_id, 'theme': self.theme,
                'task_sha256': task.sha256, 'policy_epoch': self.policy_epoch,
                'mechanism_semantic_version': SEMANTIC_VERSION,
                'candidate_context_version': CONTEXT_VERSION, 'rubric_version': RUBRIC_VERSION,
                'semantic_review_sha256': digest(self.registry), 'priors_sha256': digest(self.priors),
                'source_reference_scope': None if self.manifest is None else self.manifest['scope']}
            scope = self.period_id + '/' + task.sha256 + '/' + digest(calibration_binding)
            policy = Policy(theme=self.theme, priors=self.priors, calibration_scope=scope,
                **({k: self.manifest[k] for k in ('reference_score', 'reference_period_id', 'reference_raw')}
                   if self.manifest is not None else {}))
            try:
                assets.validate(task, deck); legality = 'legal'
            except ContractError:
                legality = 'illegal'
            audit = score_construction(reviews, units, policy=policy, legality=legality,
                scope=scope, evaluation_context={'goal_id': task.sha256, 'period_id': self.period_id})
            audit['calibration_binding'] = calibration_binding
            audit['reference_mapping_scope'] = ('same explicitly selected historical Pearl objective; '
                'expert-prior reference mapping, not empirical calibration or authorization for arbitrary goals')
            # Use the facts actually retained/priced by this audit, in active
            # zones. A reviewed side fact without a swap plan cannot establish
            # that the unknown Main/Extra inventory received a numeric grade.
            # Fully reviewed, explicitly unavailable/zero-valued functions are
            # still known zero; this is an evidence check, not a positive-score
            # threshold. Unknown functions remain uncredited in partial grades.
            scored_facts={(c['key'],b['kind'],b['fact_id']) for c in audit['cards']
                if c['zone'] in ('main','extra') for b in c['blocks']}
            known_scored_facts=[(c.key,b.fact_id) for c in reviews for b in c.blocks
                if (c.key,b.kind,b.fact_id) in scored_facts and b.status in ('reviewed','unavailable')
                and 'unknown' not in b.knowledge.values()]
            audit['active_priced_context_reviewed_functions']=len(known_scored_facts)
            if any('missing_card_text' in c.unknowns for c in reviews) or not known_scored_facts:
                audit.update(score=None, score_threshold_met=None,
                    force_optimization=self.manifest is not None,
                    construction_semantics_status='unknown')
            else:
                audit['construction_semantics_status']='scoped_functions_reviewed'
            if self.tracker is not None:
                result = record_scoring_feedback(audit, self.tracker, evaluation_id=evaluation_id,
                    candidate_digest=identity['deck_multiset_sha256'], cycle_id=cycle_id,
                    goal_id=task.sha256, period_id=self.period_id)
                feedback = {'score': result['score'], 'force_optimization': result['force_optimization'],
                    'optimization_reason': result['optimization_reason'],
                    'hint': deepcopy((result.get('hint_event') or {}).get('hint')),
                    'reference_comparison_applicable': True, 'construction_strength_status': 'unknown'}
            else:
                feedback = {'score': public_result(audit), 'force_optimization': audit['force_optimization'],
                    'hint': None, 'reference_comparison_applicable': False,
                    'construction_strength_status': 'unknown'}
        private_audit = self.path.parent / (evaluation_id + '.private-audit.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        private_audit.write_text(json.dumps({'identity': identity, 'audit': audit}, ensure_ascii=False,
            indent=2) + '\n', encoding='utf-8')
        record = {**identity, 'public_feedback': feedback, 'private_audit_sha256': digest(audit)}
        self.value['construction_evaluations'].setdefault(key, []).append(record)
        self.value['evaluation_ids'][evaluation_id] = identity
        self._save()
        return deepcopy(feedback)

    def __call__(self, *, task, deck, basic_cb, assets, purpose):
        if self.logical_course_id is not None:self._assert_saved_state()
        self._task_period(task, assets)
        rows = self.value['construction_evaluations'].get(self._scope_key(task, deck), ())
        feedback = rows[-1]['public_feedback'] if rows else None
        trigger = self._cb_trigger(task)
        refs = [{'kind': 'explicit_prospective_construction_policy', 'epoch': self.policy_epoch,
                 'period_id': self.period_id, 'task_sha256': task.sha256}]
        if rows:
            refs.append({'kind': 'completed_actual_candidate_score', 'evaluation_id': rows[-1]['evaluation_id'],
                         'task_sha256': task.sha256, 'deck_multiset_sha256': _deck_key(deck)})
        if trigger is not None:
            refs.append({'kind': 'conditional_cb_optimization_signal', 'attempt_id': trigger})
        reasons = []
        if self.period_id in HISTORICAL_PERIODS:
            if feedback is None: reasons.append('actual_candidate_construction_score_required')
            elif feedback['force_optimization']:
                reasons.append(feedback.get('optimization_reason') or 'construction_optimization_required')
        requested = trigger is not None or bool(feedback and feedback['force_optimization'])
        return {**self._identity(task, deck), 'status': 'deferred' if reasons else 'admitted',
            'policy_epoch': self.policy_epoch, 'reasons': reasons, 'evidence_refs': refs,
            'signals': {'optimization_requested': requested, 'mandatory_rebuild': False,
                        'hint_permission': bool(feedback and feedback.get('hint'))}}

    def public_feedback(self, *, task, deck):
        """Only released scalar feedback and anonymous hints may reach models."""
        rows = self.value['construction_evaluations'].get(self._scope_key(task, deck), ())
        return deepcopy(rows[-1]['public_feedback']) if rows else None


def load_course_admission_policy(course, target, *, private_root=None):
    """Factory used by the real course after construction of its host object.

    Historical scoring is enabled only for the explicit Pearl theme selection.
    Autonomous periods continue through legality/CB without importing old
    reference anchors; callers may supply their own goal-conditioned priors.
    """
    period = course.config['period_id']
    theme_ids = course.config.get('construction_theme_ids', ())
    explicit = course.config.get('construction_scoring', {})
    theme = explicit.get('theme')
    priors = explicit.get('priors')
    if period in HISTORICAL_PERIODS and 'setcode-181' in theme_ids:
        if explicit and (theme != 'pearl_grave_fusion' or priors != PEARL_PRIORS):
            raise ContractError('historical reference priors must match the selected calibrated goal')
        theme, priors = 'pearl_grave_fusion', deepcopy(PEARL_PRIORS)
    if private_root is None:
        private_root = Path(__file__).resolve().parents[3] / 'evaluator-private' / 'reference-scoring'
    private_root = Path(private_root)
    logical_id = course.config['course_id']
    name = digest({'course': logical_id, 'period_id': period, 'policy_epoch': POLICY_EPOCH})[:32]
    state_path = private_root / 'courses' / name / 'admission-state.json'
    expected = getattr(course, '_admission_state_reference', None)
    if expected is not None and not state_path.exists():
        raise ContractError('checkpoint private admission state is missing; preserve the original ledger')
    if not state_path.exists():
        for old_path in (private_root / 'courses').glob('*/admission-state.json'):
            old = json.loads(old_path.read_text(encoding='utf-8')).get('binding', {})
            same_epoch = (old.get('period_id') == period and old.get('policy_epoch') == POLICY_EPOCH)
            if same_epoch and old.get('logical_course_id') in (None, logical_id):
                # Earlier target-hashed states did not retain a reversible
                # course identity. Never interpret relocation as a fresh ledger.
                raise ContractError('compatible legacy private admission state requires explicit migration')
    host = CourseAdmissionPolicy(state_path, private_root=private_root, period_id=period,
        theme=theme, priors=priors, logical_course_id=logical_id)
    if not host.path.exists():host._save()
    return host
