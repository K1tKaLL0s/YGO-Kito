"""Optional advisory seam: explicit recalled candidates in, source-bound scores out."""

from dataclasses import dataclass, replace

import torch

from .contracts import FAMILIES, GROUP_FACTORS, ROLES, FactorContractError, Group, RoleInput, fields, text
from .network import encode_batch
from .functional_units import FunctionalContract, assess_unit
from .training import HEADS, RoleTrainer


@dataclass(frozen=True)
class Candidate:
    candidate_ref: str
    example: RoleInput
    target_key: str
    recall_source: str
    legality: str = "unknown"
    legality_ref: str = ""

    def __post_init__(self):
        for name in ("candidate_ref", "target_key", "recall_source"):
            text(getattr(self, name), name)
        if not isinstance(self.example, RoleInput) or self.target_key not in {group.key for group in self.example.groups}:
            raise FactorContractError("candidate requires its target group in a typed role input")
        if self.legality not in ("pass", "fail", "unknown"):
            raise FactorContractError("external legality must be pass/fail/unknown")
        text(self.legality_ref, "legality evidence", optional=self.legality == "unknown")

    def to_dict(self):
        return dict(candidate_ref=self.candidate_ref, example=self.example.to_dict(), target_key=self.target_key,
                    recall_source=self.recall_source, legality=self.legality, legality_ref=self.legality_ref)

    @classmethod
    def from_dict(cls, value):
        fields(value, ("candidate_ref", "example", "target_key", "recall_source", "legality", "legality_ref"))
        return cls(**dict(value, example=RoleInput.from_dict(value["example"])))


def _coverage(factors):
    values = [factors.get(name) for name in FAMILIES[factors.family]]
    known = [value for value in values if value.value is not None]
    return dict(known_fraction=len(known) / len(values),
                reliability_coverage=sum(value.confidence * (1 - value.uncertainty) for value in known) / len(values),
                mean_observed_uncertainty=None if not known else sum(value.uncertainty for value in known) / len(known))


class CandidateScorer:
    def __init__(self, trainer, *, calibrator=None):
        if not isinstance(trainer, RoleTrainer):
            raise FactorContractError("independent role trainer required")
        self.trainer = trainer
        if calibrator is not None and not callable(calibrator):
            raise FactorContractError("explicit fitted calibration provider must be callable")
        self.calibrator = calibrator
        if calibrator is not None and hasattr(calibrator, 'check_base'):
            calibrator.check_base(trainer)

    def score_graph(self, build, *, task, query_budget=32768):
        """All fact-domain queries for one head, in blocks; no model discovery.

        Training counts only permit raw diagnostics. The service independently
        checks host-published capability evidence before applying calibration.
        """
        from itertools import islice
        from .contracts import TASK_DOMAINS
        from .task_queries import CATEGORY_COORDINATES, iter_queries, query_domain
        if self.calibrator is not None and hasattr(self.calibrator, 'check_base'):
            self.calibrator.check_base(self.trainer)
        if self.trainer.model.config.feature_schema != "axis-graph-v3":
            raise FactorContractError("v3 candidate scoring requires an explicitly injected v3 trainer")
        if type(query_budget) is not int or not 1 <= query_budget <= 1000000:
            raise FactorContractError("bounded query budget required")
        if self.trainer.head_status(task) not in ("trained_uncalibrated", "weakly_supervised_uncalibrated"):
            raise FactorContractError("untrained/engineering heads cannot provide recognition conclusions")
        domain = query_domain(build.input, build.graph, build.candidates.to_dict())
        queries = list(islice(iter_queries(domain, task), query_budget + 1))
        if len(queries) > query_budget:
            raise FactorContractError("whole-head query budget exceeded; no partial candidate scores")
        if not queries:
            return dict(raw_prediction=(), calibrated_scores=(), applied_prediction=())
        model, prior_mode = self.trainer.model, self.trainer.model.training
        if self.trainer.lora is not None:
            self.trainer.lora.check_base()
        model.eval()
        try:
            with torch.inference_mode():
                batch = encode_batch((build,), device=self.trainer.device, config=model.config)
                encoded = model(batch)
                rows = []
                for start in range(0, len(queries), 32):
                    block = queries[start:start + 32]
                    logits = model.score_queries(encoded, batch, [(0, *q) for q in block])
                    categorical = task in CATEGORY_COORDINATES
                    values = (logits.softmax(-1) if categorical else logits.sigmoid()).tolist()
                    for (_, subject, coordinate), value in zip(block, values):
                        prediction = dict(zip(TASK_DOMAINS[task], value)) if categorical else value
                        rows.append(dict(task=task, subject=list(subject), coordinate=coordinate, value=prediction))
        finally:
            model.train(prior_mode)
        calibrated = () if self.calibrator is None else self.calibrator(task, tuple(rows))
        # A calibrator supplies explicit rows for both layers; no default 0.5
        # threshold or class argmax is advertised as a fitted decision rule.
        if self.calibrator is not None and (not isinstance(calibrated, dict) or
                set(calibrated) != {"calibrated_scores", "applied_prediction"}):
            raise FactorContractError("calibrator must supply both explicit fitted output layers")
        return dict(raw_prediction=tuple(rows), calibrated_scores=() if not calibrated else calibrated["calibrated_scores"],
                    applied_prediction=() if not calibrated else calibrated["applied_prediction"])

    def _forward(self, example):
        if self.trainer.lora is not None:
            self.trainer.lora.check_base()
        with torch.inference_mode():
            return self.trainer.model(encode_batch((example,)))

    def score_copy_graphs(self, left, right, *, operation):
        if self.calibrator is not None and hasattr(self.calibrator, 'check_base'):
            self.calibrator.check_base(self.trainer)
        from .contracts import TASK_DOMAINS
        from .task_queries import validate_comparison
        validate_comparison(left,right,left_key="query:unit",right_key="query:unit",operation=operation)
        if (self.trainer.model.config.feature_schema != 'axis-graph-v3' or
                self.trainer.head_status('copy_preference') not in ('trained_uncalibrated', 'weakly_supervised_uncalibrated')):
            raise FactorContractError('trained v3 comparison head required')
        if self.calibrator is None:
            raise FactorContractError('copy comparison requires explicitly fitted calibration')
        model, prior = self.trainer.model, self.trainer.model.training
        if self.trainer.lora is not None:
            self.trainer.lora.check_base()
        model.eval()
        try:
            with torch.inference_mode():
                batch = encode_batch((left, right), device=self.trainer.device, config=model.config)
                encoded = model(batch)
                logits = model.graph_network.score_preference(encoded, batch, 'query:unit', 'query:unit')
                value = {k: float(v) for k, v in zip(TASK_DOMAINS['copy_preference'], logits.softmax(-1))}
        finally:
            model.train(prior)
        raw = (dict(task='copy_preference', subject=['query:unit', 'query:unit'], coordinate='preference', value=value),)
        calibrated = self.calibrator('copy_preference', raw)
        if not isinstance(calibrated, dict) or set(calibrated) != {'calibrated_scores', 'applied_prediction'}:
            raise FactorContractError('copy calibrator must supply explicit fitted output layers')
        return dict(raw_prediction=raw, **calibrated)

    def explain(self, example, target_key):
        """Finite observed-factor ablation, never a causal or rules explanation."""
        index = next((i for i, group in enumerate(example.groups) if group.key == target_key), None)
        if index is None:
            raise FactorContractError("explanation target group missing")
        baseline = self._forward(example)
        target = example.groups[index]
        effects = []
        for name, observation in target.factors.items:
            if observation.value is None:
                continue
            changed_groups = list(example.groups)
            changed_groups[index] = replace(target, factors=target.factors.without(name))
            ablated = self._forward(replace(example, groups=tuple(changed_groups)))
            effects.append(dict(factor=name, observation=observation.to_dict(),
                                utility_delta=float(baseline["utility"][0, index] - ablated["utility"][0, index]),
                                role_logit_delta={role: float(baseline["role_logits"][0, index, r] - ablated["role_logits"][0, index, r])
                                                  for r, role in enumerate(ROLES)},
                                compatibility_logit_delta=float(baseline["compatibility_logits"][0, index] -
                                                                ablated["compatibility_logits"][0, index])))
        return dict(method="observed_factor_to_unknown_ablation", causal=False, factors=effects,
                    unknown_factors=[name for name in GROUP_FACTORS if target.encoded_factors().get(name).value is None],
                    derived_unit_observations={name: value.to_dict() for name, value in target.encoded_factors().items
                                               if name not in dict(target.factors.items)},
                    context_observations=example.context.to_dict(),
                    incident_relations=[edge.to_dict() for edge in example.relations if target_key in (edge.source, edge.target)],
                    relation_absence="unknown; absent edge does not establish independence",
                    notes=list(target.notes), member_refs=list(target.member_refs))

    def score_candidates(self, candidates, *, explain=True,
                         required_factors=("activation_access", "goal_contribution", "summon_lock_risk")):
        if (not isinstance(candidates, (tuple, list)) or not 1 <= len(candidates) <= 32
                or any(not isinstance(candidate, Candidate) for candidate in candidates)):
            raise FactorContractError("1..32 explicit recalled candidates required")
        if len({candidate.candidate_ref for candidate in candidates}) != len(candidates):
            raise FactorContractError("duplicate candidate reference")
        base = candidates[0].example
        if any(c.example.context_ref != base.context_ref or c.example.context != base.context for c in candidates):
            raise FactorContractError("candidate batch must preserve the exact frozen goal/context")
        if (not isinstance(required_factors, tuple) or any(name not in GROUP_FACTORS for name in required_factors)
                or len(set(required_factors)) != len(required_factors)):
            raise FactorContractError("distinct known required factors required")
        if self.trainer.lora is not None:
            self.trainer.lora.check_base()
        with torch.inference_mode():
            output = self.trainer.model(encode_batch(tuple(candidate.example for candidate in candidates), device=self.trainer.device))
        head_status = {head: self.trainer.head_status(head) for head in HEADS}
        results = []
        for batch, candidate in enumerate(candidates):
            index = next(i for i, group in enumerate(candidate.example.groups) if group.key == candidate.target_key)
            group = candidate.example.groups[index]
            coverage = _coverage(group.encoded_factors())
            context_coverage = _coverage(candidate.example.context)
            unresolved = [name for name in required_factors if group.factors.get(name).value is None or
                          group.factors.get(name).confidence == 0 or group.factors.get(name).uncertainty == 1]
            reasons = []
            if head_status["utility"] not in ("trained_uncalibrated", "weakly_supervised_uncalibrated"):
                reasons.append("utility_" + head_status["utility"])
            if candidate.legality != "pass":
                reasons.append("external_legality_" + candidate.legality)
            if unresolved:
                reasons.append("required_factors_unknown_or_unreliable")
            if context_coverage["reliability_coverage"] == 0:
                reasons.append("context_unknown_or_unreliable")
            unit_assessment = None if group.unit is None else assess_unit(group.unit, group.member_refs)
            if unit_assessment is None:
                reasons.append("functional_unit_unknown")
            elif not unit_assessment["membership_ready"]:
                reasons.append("functional_unit_incomplete_or_unverified")
            if unit_assessment is not None and not unit_assessment["function_features_known"]:
                reasons.append("function_features_unknown")
            utility = float(output["utility"][batch, index])
            relation_coverage = []
            for other, other_group in enumerate(candidate.example.groups):
                if other != index:
                    relation_coverage.append(dict(other_key=other_group.key,
                        probability=(float(output["pair_logits"][batch, index, other].sigmoid())
                                     if head_status["pair"] in ("trained_uncalibrated", "weakly_supervised_uncalibrated") else None),
                        evidence=[edge.to_dict() for edge in candidate.example.relations
                                  if {edge.source, edge.target} == {candidate.target_key, other_group.key}]))
            result = dict(candidate_ref=candidate.candidate_ref, context_ref=candidate.example.context_ref,
                          target_key=candidate.target_key, recall_source=candidate.recall_source,
                          legality=candidate.legality, legality_ref=candidate.legality_ref,
                          advisory_score=None if reasons else utility, raw_utility=utility,
                          role_probabilities={role: (float(output["role_logits"][batch, index, r].sigmoid())
                                               if self.trainer.head_status("role:" + role) in ("trained_uncalibrated", "weakly_supervised_uncalibrated") and
                                               (role != "generic_utility" or unit_assessment is not None and unit_assessment["minimal_membership_complete"] and
                                                unit_assessment["function_features_known"]) else None)
                                              for r, role in enumerate(ROLES)},
                          diagnostic_role_probabilities={role: float(output["role_logits"][batch, index, r].sigmoid()) for r, role in enumerate(ROLES)},
                          compatibility_probability=(float(output["compatibility_logits"][batch, index].sigmoid())
                                                     if head_status["compatibility"] in ("trained_uncalibrated", "weakly_supervised_uncalibrated") else None),
                          pair_compatibility=relation_coverage, head_status=dict(head_status), calibrated=False,
                          label_protocol_sha256=self.trainer.label_protocol_sha256,
                          role_dimension_status={role: self.trainer.head_status("role:" + role) for role in ROLES},
                          functional_unit=unit_assessment,
                          adaptation=self.trainer.adaptation_status(),
                          coverage=coverage, context_coverage=context_coverage, unresolved_required_factors=unresolved,
                          abstention_reasons=reasons, rule_authority=False, advisory_only=True,
                          probability_interpretation="uncalibrated role-match estimates for the declared plan; core/support may coexist without a plan_known hard gate; current readiness is separate; no validated large/small mapping to v3")
            if explain:
                result["explanation"] = self.explain(candidate.example, candidate.target_key)
            results.append(result)
        # Preserve host order. No ID-based tie break, automatic selection or deck mutation.
        return tuple(results)


def prepare_function_candidate(context, contract, available_refs, *, candidate_ref, target_key,
                               recall_source, factor_provider, legality="unknown", legality_ref="", proposed_refs=None,
                               branch_id=None, resources=(), coverage=False, branch_factor_provider=None):
    """Resolve necessities first; request host whole-unit cost/benefit only afterward.

    The provider receives every proposed member/copy after the required unit is
    identified, including optional copies. With no explicit proposal the minimum
    unit is proposed. It must supply package-level measurements, not average a
    singleton's utility. Genericity remains attached to the minimum unit.
    This seam never edits a construction session or enumerates a whole card pool.
    """
    if not isinstance(context, RoleInput) or not isinstance(contract, FunctionalContract) or contract.context_ref != context.context_ref:
        raise FactorContractError("candidate function must match the explicit frozen context")
    assessment = assess_unit(contract, available_refs, resources=resources, coverage=coverage, branch_id=branch_id)
    if not assessment["membership_ready"]:
        return dict(status="unit_unresolved", candidate=None, assessment=assessment, cost_benefit_evaluated=False)
    if branch_id is None and assessment["overflow"]:
        return dict(status="branch_search_incomplete", candidate=None, assessment=assessment, cost_benefit_evaluated=False)
    feasible = [b for b in assessment["branches"] if b["membership_ready"] and (branch_id is None or b["branch_id"] == branch_id)]
    if len(feasible) != 1:
        return dict(status="branch_selection_required", candidate=None, assessment=assessment, cost_benefit_evaluated=False)
    selected = feasible[0]
    branch_id = selected["branch_id"]
    members = tuple(ref for ref, count in sorted(selected["members"].items()) for _ in range(count))
    if proposed_refs is not None:
        from collections import Counter
        if not isinstance(proposed_refs, tuple) or not 1 <= len(proposed_refs) <= 128:
            raise FactorContractError("bounded explicit proposed member tuple required")
        if Counter(proposed_refs) - Counter(available_refs):
            raise FactorContractError("proposed package contains unavailable members/copies")
        members = proposed_refs
    # Both the default minimum and an explicit proposal are rechecked against
    # the selected recursive branch before any cost provider is invoked.
    assessment = assess_unit(contract, members, resources=resources, coverage=coverage, branch_id=branch_id)
    if not assessment["membership_ready"]:
        return dict(status="unit_unresolved", candidate=None, assessment=assessment, cost_benefit_evaluated=False)
    if branch_factor_provider is None and (contract.requirements is not None or contract.state_requirements is not None or selected["branch_conditions"]):
        return dict(status="branch_cost_provider_required", candidate=None, assessment=assessment, cost_benefit_evaluated=False)
    factors = (factor_provider(members) if branch_factor_provider is None else
               branch_factor_provider(members, assessment))
    group = Group(target_key, factors, members, ("whole-unit host factors; no package-to-member label projection",), contract)
    example = replace(context, groups=context.groups + (group,))
    candidate = Candidate(candidate_ref, example, target_key, recall_source, legality, legality_ref)
    return dict(status="unit_prepared", candidate=candidate, assessment=assessment, cost_benefit_evaluated=True)
