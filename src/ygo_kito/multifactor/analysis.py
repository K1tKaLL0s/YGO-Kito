"""Fact-bound analysis services. Importing this module never loads a model."""
from collections import Counter
from dataclasses import asdict, dataclass, field, replace

from .contracts import (DECK_SECTIONS, ROLES, AnalysisContext, AnalysisRequestContext,
                        AnalysisValue, CapabilityStatus, CopyChange, CopyComparison,
                        DeckAnalysis, DeckSpec, FactorContractError, RoleInput, UnitAssessment, UnitSpec,
                        digest, text)
from .axis_candidates import CandidateBudget
from .conditions import Resource, SolverBudget
from .functional_units import FunctionalContract, assess_unit as assess_function_contract
from .semantics import GraphBudget, build_analysis_graph
from .task_queries import LEARNED_TASKS, query_domain, validate_query


def migrate_v2_input(value, *, analysis_mode, deck=None, unit=None, visible_state=None,
                     format="unknown", period="unknown", rule_version="unknown",
                     public_resources=None, insertion=None):
    legacy = RoleInput.from_dict(value)
    if legacy.analysis_mode is not None:
        raise FactorContractError("migration requires legacy v2/v7 input")
    converted = replace(legacy, mechanism=None, analysis_mode=analysis_mode,
                        analysis_context=AnalysisContext(format, period, rule_version, public_resources),
                        deck=deck, unit_definition=unit, visible_state=visible_state, insertion=insertion)
    result = converted.to_dict()
    if legacy.mechanism is not None:
        # Record writers retain this annotation outside model observations.
        result["provenance"] = {"legacy_mechanism": legacy.mechanism.to_dict()}
    return result


@dataclass(frozen=True)
class AnalysisBudget:
    graph: GraphBudget = field(default_factory=GraphBudget)
    candidates: CandidateBudget = field(default_factory=CandidateBudget)
    solver: SolverBudget = field(default_factory=SolverBudget)
    queries: int = 32768

    def __post_init__(self):
        if (not isinstance(self.graph, GraphBudget) or not isinstance(self.candidates, CandidateBudget)
                or not isinstance(self.solver, SolverBudget) or type(self.queries) is not int
                or not 1 <= self.queries <= 1000000):
            raise FactorContractError("typed, bounded analysis budgets required")


@dataclass(frozen=True)
class AnalysisFacts:
    """Only observations from a host provider, never training records or labels."""
    card_rows: dict = field(default_factory=dict)
    effect_snapshots: dict = field(default_factory=dict)
    structure_links: tuple = ()
    function_seeds: tuple = ()
    unit_contracts: tuple = ()
    source_ref: str = "supplied_effect_facts"
    confidence: float = 0.55
    catalog_digest: str = ""
    resources: tuple = ()

    def __post_init__(self):
        if not isinstance(self.card_rows, dict) or not isinstance(self.effect_snapshots, dict):
            raise FactorContractError("code-keyed fact mappings required")
        if not isinstance(self.unit_contracts, tuple) or any(not isinstance(c, FunctionalContract) for c in self.unit_contracts):
            raise FactorContractError("typed source-declared function contracts required")
        if not isinstance(self.resources, tuple) or any(not isinstance(r, Resource) for r in self.resources):
            raise FactorContractError("typed inventory-bound resources required")


def _context(value):
    if isinstance(value, AnalysisRequestContext):
        return value
    if isinstance(value, AnalysisContext):
        return AnalysisRequestContext(rules=value)
    return AnalysisRequestContext.from_dict(value)


def _deck(value, *, optional=False):
    if value is None and optional:
        return None
    return value if isinstance(value, DeckSpec) else DeckSpec.from_dict(value)


def _available(deck):
    # Side is an independent region, not an active companion before siding.
    if deck is None:
        return ()
    return tuple(f"card:{code}" for section in (deck.main, deck.extra) if section is not None
                 for code, count in section for _ in range(count))


def _summary(deck):
    result = {}
    for section in DECK_SECTIONS:
        stock = None if deck is None else getattr(deck, section)
        size = None if stock is None else sum(n for _, n in stock)
        result[section] = dict(status="unknown" if stock is None else "known", count=size,
            reason_code="SECTION_NOT_PROVIDED" if stock is None else "ACTUAL_SECTION_COUNT",
            density_status="unknown" if stock is None else "not_applicable" if size == 0 else "known",
            cards=[] if stock is None else [dict(card_id=c, copies=n, density=n / size) for c, n in stock])
    return result


def _legality(deck, context):
    external = context.external_legality
    if external is None:
        return AnalysisValue(reason_code="NO_EXTERNAL_LEGALITY")
    if (external.subject_deck != deck or external.context_ref != context.context_ref
            or external.rules != context.rules or external.declared_goal != context.declared_goal):
        return AnalysisValue(reason_code="EXTERNAL_LEGALITY_SCOPE_MISMATCH")
    return AnalysisValue("known", external.result, "EXTERNAL_RESULT", external.producer,
                         external.version, external.evidence_refs)


def _contract_assessment(contract, deck, context, budget, *, available=None):
    if contract.context_ref != context.context_ref or contract.period_ref not in (None, context.rules.period):
        raise FactorContractError("functional facts must bind the requested context and period")
    members = _available(deck) if available is None else available
    if len(members) > 128:
        return dict(contract_ref=contract.key, function_ref=contract.function_ref,
                    structural_status="unknown", state_readiness="unknown", branches=[],
                    reason_code="MEMBER_ASSESSMENT_BUDGET")
    result = assess_function_contract(contract, members, resources=context.rules.public_resources or (),
        coverage=context.resource_coverage, state_provided=context.visible_state is not None, budget=budget)
    if available is None and (deck is None or deck.main is None or deck.extra is None):
        # Absence cannot prove a missing member when an active section is unknown.
        if result["structural_status"] == "partial":
            result.update(structural_status="unknown", state_readiness="unknown", current_function_ready=None)
        result['missing_members_status'] = 'unknown'
        for branch in result["branches"]:
            if branch["missing_members"]:
                branch.update(structural_status="unknown", state_readiness="unknown", membership_ready=False,
                              reason_code="RECEIVER_SECTION_UNKNOWN", missing_members_status='unknown')
                branch['requirement_assessment'] = dict(branch['requirement_assessment'], satisfied=None,
                    structural_status='unknown', reason_code='RECEIVER_SECTION_UNKNOWN')
    return result


class RoleAnalyzer:
    def __init__(self, fact_provider=None, *, scorer=None, capabilities=None, budget=None, environment_provider=None):
        if fact_provider is not None and not callable(fact_provider):
            raise FactorContractError("optional fact provider must be callable")
        self.fact_provider, self.scorer = fact_provider, scorer
        self.budget = budget if budget is not None else AnalysisBudget()
        if not isinstance(self.budget, AnalysisBudget):
            raise FactorContractError("typed analysis budget required")
        capabilities = {} if capabilities is None else capabilities
        if not isinstance(capabilities, dict) or any(not isinstance(v, CapabilityStatus) for v in capabilities.values()):
            raise FactorContractError("explicit typed capability mapping required")
        self.capabilities = dict(capabilities)
        if environment_provider is not None and (not callable(getattr(environment_provider,"evaluate",None)) or
                not isinstance(getattr(environment_provider,"capability",None),CapabilityStatus) or
                environment_provider.capability.status!="available"):
            raise FactorContractError("environment provider requires explicit validated calibrated capability")
        self.environment_provider = environment_provider

    def _capabilities(self):
        caps = {name: CapabilityStatus("untrained" if self.scorer is not None else "unavailable")
                for name in LEARNED_TASKS}
        caps.update(state_readiness=CapabilityStatus("deterministic_only"),
                    function_facts=CapabilityStatus("deterministic_only"),
                    requirements=CapabilityStatus("deterministic_only"), environment_value=CapabilityStatus("disabled"))
        caps.update(self.capabilities)
        caps["environment_value"] = (CapabilityStatus("disabled") if self.environment_provider is None
                                     else self.environment_provider.capability)
        return caps

    def _scores(self, build, context, caps):
        raw, calibrated, applied, failures = [], [], [], []
        if self.scorer is None:
            return raw, calibrated, applied, failures
        domain = query_domain(build.input, build.graph, build.candidates.to_dict())
        for task in LEARNED_TASKS:
            if task == 'copy_preference' or task == 'receiver_compatibility' and build.input.deck is None:
                continue  # Copy preferences require an actual pair/operation.
            cap = caps[task]
            if cap.status not in ("available", "trained_uncalibrated", "weakly_supervised_uncalibrated"):
                continue
            if build.candidates.overflow and task != 'mechanism':
                caps[task] = CapabilityStatus('failed')
                failures.append(dict(capability=task, reason_code='CANDIDATE_ENUMERATION_INCOMPLETE'))
                continue
            try:
                output = self.scorer.score_graph(build, task=task, query_budget=self.budget.queries)
                if not isinstance(output, dict) or not set(output) <= {"raw_prediction", "calibrated_scores", "applied_prediction"}:
                    raise FactorContractError("scorer must return explicit prediction layers")
                rows_by_layer, keys_by_layer = {}, {}
                for layer in ("raw_prediction", "calibrated_scores", "applied_prediction"):
                    rows = output.get(layer, ())
                    if not isinstance(rows, (tuple, list)) or len(rows) > self.budget.queries:
                        raise FactorContractError("scorer query budget exceeded")
                    seen = set()
                    for row in rows:
                        if not isinstance(row, dict) or set(row) != {"task", "subject", "coordinate", "value"} or row["task"] != task:
                            raise FactorContractError("scorer row must bind the requested task/query")
                        validate_query(domain, task, row["subject"], row["coordinate"])
                        key = digest((row["subject"], row["coordinate"]))
                        if key in seen:
                            raise FactorContractError("duplicate scored query")
                        seen.add(key)
                        from .task_queries import CATEGORY_COORDINATES
                        from .contracts import TASK_DOMAINS, unit as probability
                        if task in CATEGORY_COORDINATES:
                            if layer == "applied_prediction":
                                if row["value"] not in TASK_DOMAINS[task]:
                                    raise FactorContractError("applied category outside task domain")
                            else:
                                if not isinstance(row["value"], dict) or set(row["value"]) != set(TASK_DOMAINS[task]):
                                    raise FactorContractError("categorical probabilities require complete vocabulary")
                                for value in row["value"].values():
                                    probability(value, "prediction probability")
                                if abs(sum(row["value"].values()) - 1) > 1e-5:
                                    raise FactorContractError("categorical probabilities must sum to one")
                        else:
                            probability(float(row["value"]) if type(row["value"]) is bool and layer == "applied_prediction"
                                        else row["value"], "prediction probability")
                    rows_by_layer[layer] = list(rows)
                    keys_by_layer[layer] = seen
                if (not keys_by_layer["calibrated_scores"] <= keys_by_layer["raw_prediction"] or
                        not keys_by_layer["applied_prediction"] <= keys_by_layer["calibrated_scores"]):
                    raise FactorContractError("calibrated/applied queries must bind their preceding prediction layer")
                raw.extend(rows_by_layer["raw_prediction"])
                if cap.status == "available" and rows_by_layer["calibrated_scores"]:
                    calibrated.extend(rows_by_layer["calibrated_scores"])
                    if context.mode == "assist":
                        applied.extend(rows_by_layer["applied_prediction"])
                elif cap.status == "available":
                    caps[task] = replace(cap, status="trained_uncalibrated", validated=False, calibrated=False)
                    failures.append(dict(capability=task, reason_code="CALIBRATED_OUTPUT_MISSING"))
            except Exception as error:
                # A task-specific failure never disables unrelated heads/facts.
                caps[task] = CapabilityStatus("failed")
                failures.append(dict(capability=task, reason_code="QUERY_BUDGET_EXCEEDED" if isinstance(error, FactorContractError)
                    and 'budget' in str(error).lower() else "SCORER_UNAVAILABLE", detail=type(error).__name__))
        return raw, calibrated, applied, failures

    def _analyze(self, deck, context, unit=None):
        caps, summary = self._capabilities(), _summary(deck)
        base = dict(context_ref=context.context_ref, mode=context.mode, declared_goal=context.declared_goal,
                    deck_summary=summary, legality=_legality(deck, context))
        genericity = {name: AnalysisValue(reason_code="CAPABILITY_NOT_APPLIED").to_dict()
                      for name in ("transferability", "receiver_compatibility", "state_readiness", "environment_value")}
        if deck is None:
            genericity["receiver_compatibility"] = AnalysisValue("not_applicable", reason_code="NO_RECEIVER").to_dict()
        if context.mode == "off":
            return DeckAnalysis(**base, capabilities={k: v.to_dict() for k, v in caps.items()}, genericity=genericity,
                                unresolved=({"reason_code": "RECOGNITION_OFF"},)), (), None
        facts, failures = AnalysisFacts(), []
        if self.fact_provider is not None:
            try:
                facts = self.fact_provider(deck, context, unit)
                if not isinstance(facts, AnalysisFacts):
                    raise FactorContractError("fact provider must return AnalysisFacts")
            except Exception as error:
                facts = AnalysisFacts()
                failures.append(dict(capability="function_facts", reason_code="FACT_PROVIDER_UNAVAILABLE", detail=type(error).__name__))
                for name in ("function_facts", "requirements"):
                    caps[name] = CapabilityStatus("failed")
        if facts.resources:
            context = replace(context, rules=replace(context.rules,
                public_resources=tuple(context.rules.public_resources or ()) + facts.resources))
        mode = "deck_analysis" if unit is None else "state_evaluation" if context.visible_state is not None else "unit_analysis"
        example = RoleInput(context.context_ref, context.factors, (), analysis_mode=mode,
                            analysis_context=context.rules, deck=deck, unit_definition=unit, visible_state=context.visible_state)
        requirements = []
        for contract in facts.unit_contracts:
            if unit is not None and contract.function_ref != unit.function_id:
                continue
            try:
                requirements.append(_contract_assessment(contract, deck, context, self.budget.solver))
            except FactorContractError as error:
                requirements.append(dict(contract_ref=contract.key, function_ref=contract.function_ref,
                    structural_status="unknown", state_readiness="unknown", branches=[],
                    reason_code="CONTRACT_ASSESSMENT_UNAVAILABLE", detail=str(error)))
        if any(r['state_readiness'] != 'unknown' for r in requirements):
            readiness = [dict(contract_ref=r['contract_ref'], function_ref=r['function_ref'],
                assessment=AnalysisValue('known', r['state_readiness'], 'DETERMINISTIC_CONTRACT').to_dict()
                if r['state_readiness'] != 'unknown' else AnalysisValue(reason_code='STATE_OR_REQUIREMENTS_UNKNOWN').to_dict())
                for r in requirements]
            genericity["state_readiness"] = AnalysisValue("known", readiness, "PER_FUNCTION_CONTRACT_ASSESSMENTS",
                "multifactor.functional_units", "v3").to_dict()
        try:
            build = build_analysis_graph(example, **{name: getattr(facts, name) for name in facts.__dataclass_fields__ if name != 'resources'},
                                         budget=self.budget.graph, candidate_budget=self.budget.candidates)
        except (FactorContractError, TypeError, KeyError) as error:
            caps['function_facts'] = CapabilityStatus('failed')
            return DeckAnalysis(**base, capabilities={k: v.to_dict() for k, v in caps.items()}, genericity=genericity,
                requirements=tuple(requirements), requirement_assessment=tuple(requirements),
                unresolved=tuple(failures) + (dict(reason_code="GRAPH_UNAVAILABLE", detail=str(error)),)), facts.unit_contracts, None
        units, functions = [], []
        available = Counter(_available(deck))
        for candidate in build.candidates.units + build.candidates.candidates:
            row = candidate.to_dict()
            missing = {r: n - available[r] for r, n in candidate.members if available[r] < n}
            row.update(status="known", reason_code="OBSERVED_FUNCTION_CANDIDATE", completeness=(
                "unknown" if deck is None or deck.main is None or deck.extra is None else "partial" if missing else "complete"),
                missing_members=missing, rule_authority=False, contribution_score=None)
            row["concentration"] = {}
            codes = {int(ref[5:]) for ref, _ in candidate.members if ref.startswith("card:") and ref[5:].isdigit()}
            for section in DECK_SECTIONS:
                stock = None if deck is None else getattr(deck, section)
                size = summary[section]["count"]
                copies = None if stock is None else sum(n for c, n in stock if c in codes)
                row["concentration"][section] = dict(copies=copies, denominator=size,
                    value=None if not size else copies / size, status=summary[section]["density_status"])
            units.append(row)
            for function in candidate.functions:
                functions.append(dict(candidate_ref=candidate.candidate_id, function=function,
                    status="known", reason_code="OBSERVED_FUNCTION_FACT", evidence_refs=list(candidate.evidence_refs)))
        raw, calibrated, applied, score_failures = self._scores(build, context, caps)
        if self.environment_provider is not None:
            try:
                estimate=self.environment_provider.evaluate(build,context)
                from .contracts import unit as probability
                for key in ("raw","calibrated","value"):
                    probability(estimate[key],"environment "+key)
                cap=caps["environment_value"]
                if estimate.get("producer")!=cap.producer or estimate.get("version")!=cap.version or not estimate.get("environment_id"):
                    raise FactorContractError("environment estimate provenance differs")
                row=dict(task="environment_value",subject=["query:environment"],coordinate="value")
                raw.append(dict(row,value=estimate["raw"]))
                calibrated.append(dict(row,value=estimate["calibrated"]))
                if context.mode=="assist":
                    applied.append(dict(row,value=estimate["value"]))
                    genericity["environment_value"]=AnalysisValue("known",estimate,"VALIDATED_ENVIRONMENT_CAPABILITY",
                        cap.producer,cap.version,cap.evidence_refs).to_dict()
            except Exception as error:
                caps["environment_value"]=CapabilityStatus("failed")
                score_failures.append(dict(capability="environment_value",reason_code="ENVIRONMENT_UNAVAILABLE",detail=type(error).__name__))
        for name in ("transferability", "receiver_compatibility"):
            values = [r for r in applied if r["task"] == name and (unit is None or r["subject"][0] == "query:unit")]
            if values and not (deck is None and name == "receiver_compatibility"):
                genericity[name] = AnalysisValue("known", values, "VALIDATED_CAPABILITY",
                    caps[name].producer, caps[name].version, caps[name].evidence_refs).to_dict()
        derived = {role: AnalysisValue(reason_code="LEGACY_MAPPING_UNAVAILABLE").to_dict() for role in ROLES}
        for role in ("strategic_core", "support_role", "generic_utility"):
            values = [r for r in applied if r["task"] == "legacy:" + role]
            if values:
                derived[role] = AnalysisValue("known", values, "VALIDATED_LEGACY_HEAD").to_dict()
        derived.update(dependency_edges=[e.to_dict() for e in build.graph.edges if e.kind in ("requires", "calls", "provides", "conflict")],
                       starting_resources=None if context.rules.public_resources is None else [r.to_dict() for r in context.rules.public_resources],
                       candidate_overflow=build.candidates.overflow, candidate_reasons=list(build.candidates.reasons))
        result = DeckAnalysis(**base, capabilities={k: v.to_dict() for k, v in caps.items()}, units=tuple(units),
            axis_memberships=tuple(dict(candidate_ref=c.candidate_id, proposed_members=list(c.members),
                predictions=[r for r in applied if r['task'] == 'axis_membership' and r['subject'][0] == c.candidate_id],
                status="known" if any(r['task'] == 'axis_membership' and r['subject'][0] == c.candidate_id for r in applied) else "unknown",
                reason_code="PER_MEMBER_CAPABILITY_OUTPUT" if any(r['task'] == 'axis_membership' and r['subject'][0] == c.candidate_id for r in applied)
                    else "CANDIDATE_SUPPORT_IS_NOT_PREDICTED_MEMBERSHIP") for c in build.candidates.candidates),
            functions=tuple(functions), requirements=tuple(requirements), genericity=genericity, raw_prediction=tuple(raw),
            derived_summary=derived, requirement_assessment=tuple(requirements), calibrated_scores=tuple(calibrated),
            applied_prediction=tuple(applied), explanation_refs=tuple(sorted({r for c in units for r in c["evidence_refs"]})),
            unresolved=tuple(failures + list(build.unresolved) + score_failures))
        return result, facts.unit_contracts, build

    def analyze_deck(self, deck, context):
        deck, context = _deck(deck), _context(context)
        return self._analyze(deck, context)[0]

    def assess_unit(self, unit, receiver_deck, context, requested_function):
        unit = unit if isinstance(unit, UnitSpec) else UnitSpec.from_dict(unit)
        context, deck = _context(context), _deck(receiver_deck, optional=True)
        text(requested_function, "requested function")
        # Each function is a separate query; package labels never propagate.
        unit = replace(unit, function_id=requested_function)
        result, contracts, _ = self._analyze(deck, context, unit)
        members = tuple(f"card:{c}" for c, n in unit.members for _ in range(n))
        definition = tuple(_contract_assessment(c, None, replace(context, visible_state=None), self.budget.solver, available=members)
                           for c in contracts if c.function_ref == requested_function)
        return UnitAssessment(**result.__dict__, unit=unit, requested_function=requested_function,
                              definition_assessment=definition)

    def compare_copy_change(self, base_deck, add_card, remove_card, functions, context):
        deck, context = _deck(base_deck), _context(context)
        add = None if add_card is None else add_card if isinstance(add_card, CopyChange) else CopyChange.from_dict(add_card)
        remove = None if remove_card is None else remove_card if isinstance(remove_card, CopyChange) else CopyChange.from_dict(remove_card)
        if add is None and remove is None:
            raise FactorContractError("an actual add and/or remove operation is required")
        if not isinstance(functions, (tuple, list)) or not functions or len(set(functions)) != len(functions):
            raise FactorContractError("distinct requested comparison functions required")
        for function in functions:
            text(function, "comparison function")
        changed = {section: None if getattr(deck, section) is None else Counter(dict(getattr(deck, section))) for section in DECK_SECTIONS}
        for operation, sign in ((remove, -1), (add, 1)):
            if operation is None:
                continue
            stock = changed[operation.section]
            if stock is None:
                raise FactorContractError("cannot edit an unknown deck section")
            if sign == -1 and stock[operation.card_id] < operation.quantity:
                raise FactorContractError("copy removal exceeds actual section inventory")
            stock[operation.card_id] += sign * operation.quantity
        after_deck = DeckSpec(**{s: None if stock is None else tuple((c, n) for c, n in sorted(stock.items()) if n)
                                 for s, stock in changed.items()})
        # Full re-observation recomputes calls/dependencies/resource conflicts and
        # section denominators; neither result reuses the other's feature graph.
        before, after = self.analyze_deck(deck, context), self.analyze_deck(after_deck, context)
        differences = dict(section_counts={s: None if getattr(deck, s) is None else
            after_deck.section_counts()[s] - deck.section_counts()[s] for s in DECK_SECTIONS},
            before_functions=list(before.functions), after_functions=list(after.functions),
            before_requirements=list(before.requirement_assessment), after_requirements=list(after.requirement_assessment),
            before_dependencies=before.derived_summary.get("dependency_edges", []),
            after_dependencies=after.derived_summary.get("dependency_edges", []),
            recomputed=("inventory", "dependencies", "call_targets", "resource_conflicts", "section_denominators"),
            contact_probability=self._contact(deck, after_deck, add or remove, context),
            joint_success=AnalysisValue(reason_code="JOINT_CONDITIONS_AND_RESOURCES_REQUIRED").to_dict())
        operation = dict(add=None if add is None else asdict(add),
            remove=None if remove is None else asdict(remove),
            kind="addition" if remove is None else "reduction" if add is None else "replacement" if add.quantity == remove.quantity else "mixed_change")
        preferences = self._copy_preferences(deck, after_deck, functions, context, operation) if add is not None and remove is not None else ()
        differences['function_preferences'] = preferences
        preference = (preferences[0]['assessment'] if len(preferences) == 1 else
            AnalysisValue(reason_code='FUNCTION_AGGREGATION_NOT_DECLARED' if len(preferences) > 1 else
                          'REPLACEMENT_UNSPECIFIED' if add is None or remove is None else 'NO_VALIDATED_PAIR_COMPARISON'))
        return CopyComparison(before, after, operation, differences, tuple(functions), preference)

    def _copy_preferences(self, before, after, functions, context, operation):
        cap = self._capabilities()['copy_preference']
        if context.mode != 'assist' or cap.status != 'available' or self.scorer is None:
            return ()
        result = []
        for function in functions:
            assessment = AnalysisValue(reason_code='PAIR_COMPARISON_UNAVAILABLE')
            diagnostic = {}
            try:
                builds = []
                for deck in (before, after):
                    if any(getattr(deck, z) is None for z in ('main', 'extra')):
                        raise FactorContractError('copy preference requires complete active inventory')
                    members = Counter(dict(deck.main)) + Counter(dict(deck.extra))
                    unit = UnitSpec('whole_configuration', tuple(sorted(members.items())), function)
                    _, _, build = self._analyze(deck, context, unit)
                    if build is None:
                        raise FactorContractError('comparison graph unavailable')
                    builds.append(build)
                diagnostic = self.scorer.score_copy_graphs(*builds, operation=operation)
                from .contracts import TASK_DOMAINS, fields, unit as probability
                fields(diagnostic, ('raw_prediction', 'calibrated_scores', 'applied_prediction'))
                for layer in ('raw_prediction', 'calibrated_scores', 'applied_prediction'):
                    rows = diagnostic[layer]
                    if not isinstance(rows, (tuple, list)) or len(rows) != 1:
                        raise FactorContractError('single explicit cross-configuration comparison required')
                    row = fields(rows[0], ('task', 'subject', 'coordinate', 'value'))
                    if row['task'] != 'copy_preference' or tuple(row['subject']) != ('query:unit', 'query:unit') or row['coordinate'] != 'preference':
                        raise FactorContractError('copy preference query scope differs')
                    if layer == 'applied_prediction':
                        if row['value'] not in TASK_DOMAINS['copy_preference']:
                            raise FactorContractError('invalid copy preference category')
                    else:
                        fields(row['value'], TASK_DOMAINS['copy_preference'])
                        for value in row['value'].values():
                            probability(value, 'copy preference probability')
                        if abs(sum(row['value'].values()) - 1) > 1e-5:
                            raise FactorContractError('copy preference distribution is not normalized')
                assessment = AnalysisValue('known', diagnostic['applied_prediction'][0]['value'], 'VALIDATED_PAIR_COMPARISON',
                                           cap.producer, cap.version, cap.evidence_refs)
            except Exception as error:
                diagnostic = dict(reason_code='PAIR_COMPARISON_UNAVAILABLE', detail=type(error).__name__)
            result.append(dict(function=function, assessment=assessment, prediction=diagnostic))
        return tuple(result)

    @staticmethod
    def _contact(before, after, operation, context):
        sample = context.sampling
        if sample is None:
            return AnalysisValue(reason_code="SAMPLING_NOT_DECLARED").to_dict()
        from ..construction_relations import single_event_probabilities
        values = []
        for deck in (before, after):
            stock = getattr(deck, sample.section)
            if stock is None or sample.draws > sum(n for _, n in stock):
                return AnalysisValue(reason_code="SAMPLING_POPULATION_UNKNOWN_OR_INSUFFICIENT").to_dict()
            values.append(single_event_probabilities(sum(n for _, n in stock), dict(stock).get(operation.card_id, 0), sample.draws))
        return AnalysisValue("known", dict(card_id=operation.card_id, section=sample.section,
            before=values[0], after=values[1], interpretation="single_card_contact_not_function_success"),
            "DECLARED_SINGLE_SAMPLE", "construction_relations.single_event_probabilities", "existing").to_dict()
