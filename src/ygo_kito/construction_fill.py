"""Stage 3 adapters to existing fill/rank/list/goal interfaces.

Text reviews are explicit, source-bound assessments, not a new effect parser.
The existing goal verifier cannot certify an arbitrary lightweight graph as a CB.
"""

from dataclasses import asdict, dataclass
from copy import deepcopy
import math

from .build_contracts import DeckParts, digest
from .construction_logic import ConstructionLogic, LogicTag, reachable, select_main_axes, short
from .proof_visibility import without_private_selection_key
from .validation import ContractError, array, fields, member


@dataclass(frozen=True)
class NodeBinding:
    node_id: str
    card_ids: tuple[int, ...]

    def __post_init__(self):
        from .validation import integer
        short(self.node_id, "bound node")
        if not isinstance(self.card_ids, tuple) or not 1 <= len(self.card_ids) <= 16:
            raise ContractError("bounded card bindings required")
        for code in self.card_ids:
            integer(code, "bound card ID", 1, 2**32 - 1)
        if len(set(self.card_ids)) != len(self.card_ids):
            raise ContractError("binding identities must be distinct; deck carries quantities")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"node_id", "card_ids"})
        return cls(d["node_id"], tuple(array(d["card_ids"], "binding cards")))


@dataclass(frozen=True)
class FillProposal:
    deck: DeckParts
    bindings: tuple[NodeBinding, ...]
    connector_ids: tuple[str, ...]
    logic_sha256: str
    task_sha256: str

    def __post_init__(self):
        if not isinstance(self.deck, DeckParts):
            raise ContractError("typed concrete deck required")
        if (not isinstance(self.bindings, tuple) or not 1 <= len(self.bindings) <= 64
                or any(not isinstance(b, NodeBinding) for b in self.bindings)):
            raise ContractError("typed bounded node bindings required")
        if (not isinstance(self.connector_ids, tuple) or len(self.connector_ids) > 128
                or any(not isinstance(i, str) for i in self.connector_ids)):
            raise ContractError("bounded connector identities required")
        if len({b.node_id for b in self.bindings}) != len(self.bindings) or len(set(self.connector_ids)) != len(self.connector_ids):
            raise ContractError("duplicate active binding/connector")
        for value in (self.logic_sha256, self.task_sha256):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ContractError("fill proposal must bind task and logic digests")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"deck", "bindings", "connector_ids", "logic_sha256", "task_sha256"})
        return cls(DeckParts.from_dict(d["deck"]),
                   tuple(NodeBinding.from_dict(b) for b in array(d["bindings"], "bindings")),
                   tuple(array(d["connector_ids"], "active connectors")), d["logic_sha256"], d["task_sha256"])


@dataclass(frozen=True)
class TextEvidence:
    card_id: int
    effect_text_sha256: str
    quote: str

    def __post_init__(self):
        from .validation import integer
        integer(self.card_id, "text card ID", 1, 2**32 - 1)
        short(self.effect_text_sha256, "effect text digest")
        short(self.quote, "effect text excerpt", 512)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"card_id", "effect_text_sha256", "quote"}))


@dataclass(frozen=True)
class NodeTextReview:
    node_id: str
    status: str
    reviewed_tags: tuple[LogicTag, ...]
    evidence: tuple[TextEvidence, ...]
    source: str
    note: str

    def __post_init__(self):
        short(self.node_id, "reviewed node")
        member(self.status, "text assessment", ("satisfied", "unsatisfied", "unknown"))
        short(self.source, "text reviewer source", 256)
        short(self.note, "text review explanation", 1024)
        if (not isinstance(self.reviewed_tags, tuple) or len(self.reviewed_tags) > 12
                or any(not isinstance(t, LogicTag) for t in self.reviewed_tags)
                or len(set(self.reviewed_tags)) != len(self.reviewed_tags)):
            raise ContractError("typed distinct reviewed tags required")
        if (not isinstance(self.evidence, tuple) or len(self.evidence) > 32
                or any(not isinstance(e, TextEvidence) for e in self.evidence)):
            raise ContractError("typed bounded text evidence required")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"node_id", "status", "reviewed_tags", "evidence", "source", "note"})
        return cls(d["node_id"], d["status"], tuple(LogicTag.from_dict(t) for t in array(d["reviewed_tags"], "review tags")),
                   tuple(TextEvidence.from_dict(e) for e in array(d["evidence"], "text evidence")), d["source"], d["note"])


def existing_goal_verifier(task, deck, assets):
    """Normal production adapter; never substitutes a graph for engine actions."""
    from .build_pipeline import verify_goal
    return verify_goal(task, deck, assets)


def _check_bindings(graph, proposal):
    nodes = {n.node_id: n for n in graph.nodes}
    active = {b.node_id for b in proposal.bindings}
    connectors = {e.connector_id: e for e in graph.connectors}
    if not active <= nodes.keys() or not set(graph.goal_nodes) <= active:
        raise ContractError("fill must bind existing nodes and all graph goals")
    if not set(proposal.connector_ids) <= connectors.keys():
        raise ContractError("fill references unknown connectors")
    edges = tuple(connectors[i] for i in proposal.connector_ids)
    if any(e.source not in active or e.target not in active for e in edges):
        raise ContractError("active connector has an unbound endpoint")
    if not active <= reachable(active & set(graph.entry_nodes), edges):
        raise ContractError("active fill path is disconnected from graph entries")
    present = set(proposal.deck.main + proposal.deck.extra + proposal.deck.side)
    if any(not set(b.card_ids) <= present for b in proposal.bindings):
        raise ContractError("logic binds a card missing from concrete deck")
    # Side cards cannot execute the current pre-sideboard construction idea.
    playable = set(proposal.deck.main + proposal.deck.extra)
    if any(not set(b.card_ids) <= playable for b in proposal.bindings):
        raise ContractError("active logic cannot rely solely on side-deck cards")
    return nodes


def evaluate_fill(session, assets, proposal, *, scopes=(), text_reviewer=None, verifier=existing_goal_verifier, defer_engine=False, partial=False):
    """Reject/retain unknowns; fall back only to evidence for this task AND graph.

    text_reviewer(node, public_cards) returns NodeTextReview. public_cards contains
    full current card text and facts. Source hashes/excerpts are checked here;
    their semantics remain a labelled external assessment, requiring rule checks.
    Passing an explicit verifier=None skips engine calls and returns unverified.
    """
    session.check_goal()
    if session.logic is None:
        raise ContractError("stage 1 construction logic is required before filling")
    task, graph = session.task, session.logic
    if not isinstance(proposal, FillProposal):
        raise ContractError("typed fill proposal required")
    if proposal.task_sha256 != task.sha256 or proposal.logic_sha256 != graph.sha256:
        raise ContractError("fill proposal belongs to a different task/logic revision")
    output = {"stage": 3, "goal_sha256": session.goal_sha256, "task_sha256": task.sha256,
              "logic_sha256": graph.sha256, "card_list_legal": False, "text_reviews": [],
              "engine_validation": {"status": "not_run"}, "graph_execution_verified": False,
              "competitive_strength_verified": False, "unmet": [], "best_deck": None}

    def reject(status, message):
        session.check_goal()
        if session.logic.sha256 != graph.sha256:
            raise ContractError("logic changed during concrete fill validation")
        output.update(status=status, unmet=[message])
        prior = session._accepted_fill
        if (prior and prior["task_sha256"] == task.sha256 and prior["logic_sha256"] == graph.sha256
                and prior["scope_sha256"] == output.get("scope_sha256")):
            output["best_deck"] = deepcopy(prior["deck"])
            output["fallback"] = without_private_selection_key(prior)
        session.record_feedback("fill", message)
        from .construction_candidates import record_fill_observation
        record_fill_observation(session,proposal,output)
        return output

    axes = select_main_axes(task, assets, session.classification, scopes)
    output["stage_2"] = axes
    output["scope_sha256"] = digest({"intent": session.classification.to_dict(), "selection": axes})
    if axes["status"] not in ("selected", "skipped_broad"):
        return reject(axes["status"], "entry intent or requested theme facts must be resolved before filling")
    nodes = _check_bindings(graph, proposal)
    try:
        (assets.validate_skeleton if partial else assets.validate)(task, proposal.deck)
    except ContractError as error:
        return reject("hard_constraint_failure", str(error))
    output["card_list_legal"] = True
    for axis in axes["axes"]:
        n = sum(c in axis["card_ids"] for c in proposal.deck.main + proposal.deck.extra)
        if n < axis["minimum"]:
            return reject("theme_axis_not_satisfied", "concrete fill misses a declared main-axis minimum")
    if text_reviewer is None:
        return reject("text_review_unknown", "no concrete effect-text reviewer is available; coarse tags do not prove effects")
    for binding in proposal.bindings:
        node = nodes[binding.node_id]
        cards = tuple(dict(assets.rows[c]) for c in binding.card_ids)
        # Plain copies prevent reviewers from changing pinned card facts.
        review = text_reviewer(node, cards)
        session.check_goal()
        if session.logic.sha256 != graph.sha256:
            raise ContractError("logic changed during concrete text review")
        if not isinstance(review, NodeTextReview) or review.node_id != node.node_id:
            raise ContractError("text reviewer must return a typed review for the requested node")
        output["text_reviews"].append(asdict(review))
        def invalidate_binding():
            prior = session._accepted_fill
            if prior and any(b["node_id"] == binding.node_id and set(b["card_ids"]) == set(binding.card_ids)
                             for b in prior["bindings"]):
                session._accepted_fill = None
        if review.status != "satisfied":
            if review.status == "unsatisfied":
                invalidate_binding()
            return reject("text_review_" + review.status, review.note)
        if set(review.reviewed_tags) != set(node.tags):
            return reject("text_review_unknown", "text assessment did not cover every basic node tag")
        if {e.card_id for e in review.evidence} != set(binding.card_ids):
            return reject("text_review_unknown", "text assessment lacks evidence for each bound card")
        for evidence in review.evidence:
            desc = assets.rows[evidence.card_id]["desc"]
            if evidence.effect_text_sha256 != digest(desc) or evidence.quote not in desc:
                invalidate_binding()
                return reject("text_evidence_mismatch", "effect-text evidence does not match the current card source")
    if defer_engine:
        # Intermediate phase outputs are concrete, text-reviewed handoffs.
        # They are not CB proofs, deployed incumbents or competitive labels.
        output.update(status="axis_skeleton_ready" if partial else "concrete_candidate_cb_pending",best_deck=proposal.deck.to_dict(),
            concrete_proposal={"deck":proposal.deck.to_dict(),
                "bindings":[{"node_id":b.node_id,"card_ids":list(b.card_ids)} for b in proposal.bindings],"connector_ids":list(proposal.connector_ids),
                "logic_sha256":proposal.logic_sha256,"task_sha256":proposal.task_sha256},
            text_assessment="source_bound_external_assessment_not_formal_effect_semantics")
        return output
    if verifier is None:
        return reject("engine_validation_not_run", "concrete text was reviewed but the existing goal interface was not invoked")
    from .native import NativeError
    from .engine import EngineUnavailable
    try:
        proof = verifier(task, proposal.deck, assets)
    except (NativeError, EngineUnavailable) as error:
        return reject("engine_unavailable", str(error))
    session.check_goal()
    if session.logic.sha256 != graph.sha256:
        raise ContractError("logic changed during existing goal verification")
    output["engine_validation"] = without_private_selection_key(proof)
    from .build_semantics import accepted_status
    if proof.get("status") != accepted_status(task):
        return reject("existing_goal_unverified", "existing goal verification did not succeed: " + str(proof.get("status")))
    if proof.get("task_sha256") != task.sha256 or proof.get("deck_sha256") != digest(proposal.deck.to_dict()):
        return reject("engine_receipt_mismatch", "existing goal result is not bound to this task/deck")
    effect_verified = proof["status"] in ("verified_success", "constraints_and_route_verified")
    output.update(status="task_goal_verified_logic_unproven" if effect_verified else "list_constraints_verified_logic_unproven",
                  best_deck=proposal.deck.to_dict(),
                  unmet=["the existing goal interface does not certify arbitrary construction-logic edges as a legal CB"],
                  text_assessment="source_bound_external_assessment_not_formal_effect_semantics")
    session._accepted_fill = deepcopy({"deck": proposal.deck.to_dict(), "task_sha256": task.sha256,
                              "logic_sha256": graph.sha256, "status": output["status"],
                              "scope_sha256": output["scope_sha256"],
                              "bindings": [{"node_id": b.node_id, "card_ids": list(b.card_ids)} for b in proposal.bindings],
                              "text_reviews": output["text_reviews"], "engine_validation": proof})
    return output


def _skeleton_candidates(session, assets, binding, scopes):
    """Generate axis-only quantities; no general-purpose completion here."""
    from collections import Counter
    from .build_pipeline import EXTRA_TYPES, candidate_limit
    task, graph = session.task, session.logic
    axes = select_main_axes(task, assets, session.classification, scopes)
    if axes['status'] not in ('selected', 'skipped_broad'):
        return []
    pool = task.pool
    if axes['status'] == 'selected':
        pool = tuple(sorted({c for a in axes['axes'] for c in a['card_ids']} |
                            {r['card_id'] for r in task.requirements}))
    elif len(pool) > 128:
        from .construction_retrieval import candidate_ids
        pool, _ = candidate_ids(task, assets, graph, catalog=binding.semantic_catalog)
    matches = {node.node_id: [c for c in pool if all(
        binding._tag_status(assets.rows[c], tag)[0] == 'satisfied' for tag in node.tags)] for node in graph.nodes}
    result = []
    complete = 0
    for variant in range(min(task.candidate_budget, 16)):
        parts = {z: Counter() for z in ('main', 'extra', 'side')}
        for req in task.requirements:
            parts[req['zone']][req['card_id']] = req['minimum']
        def add(code, quantity):
            zone = 'extra' if assets.rows[code]['type'] & EXTRA_TYPES else 'main'
            maximum = next((r['maximum'] for r in task.requirements if r['zone'] == zone and r['card_id'] == code), 3)
            parts[zone][code] = max(parts[zone][code], min(quantity, maximum))
        for codes in matches.values():
            if codes:
                code = codes[(variant // 3) % len(codes)]
                add(code, 1 if assets.rows[code]['type'] & EXTRA_TYPES else 1 + variant % 3)
        for axis in axes['axes']:
            codes = axis['card_ids']
            for offset in range(len(codes)):
                present = sum(n for zone in ('main', 'extra') for c, n in parts[zone].items() if c in codes)
                if present >= axis['minimum']:
                    break
                code = codes[(offset + variant) % len(codes)]
                add(code, min(3, axis['minimum'] - present))
        if all(sum(parts[z].values()) == task.sizes[z] for z in parts):
            if complete >= candidate_limit(task):
                continue
            complete += 1
        deck = DeckParts(*(tuple(sorted(parts[z].elements())) for z in ('main', 'extra', 'side')))
        try:
            assets.validate_skeleton(task, deck)
        except ContractError:
            continue
        if deck not in result:
            result.append(deck)
    return result


def _build_axis_skeleton(session, assets, *, models, encoder, binding_provider, text_reviewer, scopes=(), layer_adapter=None):
    binding = layer_adapter.binding if layer_adapter is not None else binding_provider
    from .construction_binding import CatalogBindingAdapter
    if not isinstance(binding, CatalogBindingAdapter):
        raise ContractError('axis skeleton requires source-bound catalog binding')
    candidates = _skeleton_candidates(session, assets, binding, scopes)
    scores = [0.] * len(candidates)
    if models is not None and candidates:
        import torch
        model = models['build_goal']; mode = model.training; model.eval()
        try:
            with torch.no_grad():
                scores = model(encoder.batch(session.task, candidates)).reshape(-1).tolist()
        finally:
            model.train(mode)
        if len(scores) != len(candidates) or any(not math.isfinite(v) for v in scores):
            raise ContractError('invalid skeleton model scores')
    attempts = []
    for i in sorted(range(len(candidates)), key=lambda i: (-scores[i], i)):
        try:
            proposal = binding_provider(session.logic, session.task, candidates[i], partial=True)
            result = evaluate_fill(session, assets, proposal, scopes=scopes, text_reviewer=text_reviewer,
                verifier=None, defer_engine=True, partial=True)
        except ContractError as error:
            attempts.append({'status': 'skeleton_binding_unmatched', 'reason': str(error)})
            continue
        attempts.append(result)
        if result['status'] == 'axis_skeleton_ready':
            return dict(result, role='build_goal', selected_attempt_index=len(attempts)-1, attempts=attempts,
                candidate_count=len(candidates), candidate_decks=[d.to_dict() for d in candidates],
                model_scores=scores, model_called=models is not None, layer_evaluation=None, portfolio=[],
                unfilled={z: session.task.sizes[z] - len(getattr(proposal.deck, z)) for z in ('main','extra','side')})
    return {'status': 'axis_skeleton_unresolved', 'best_deck': None, 'attempts': attempts,
            'candidate_decks': [d.to_dict() for d in candidates], 'candidate_count': len(candidates), 'model_scores': scores}


def _fill_with_existing(session, assets, *, role="build_goal", base=None, models=None, encoder=None,
                       binding_provider=None, text_reviewer=None, scopes=(), verifier=existing_goal_verifier, defer_engine=False,mechanism_groups=None,
                       layer_adapter=None, search_offset=0, quality_policy=None, quality_evidence=None,
                       should_stop=None, pending_quality=None, recognition_provider=None, recognition_mode="off",
                       query_cursor=0, retrieval_limit=128, on_evaluation_progress=None, _comparisons=None,
                       incumbent_recognition=None):
    """Reuse existing fill/quantity generation and independent model ranking.

    Concrete CatalogBindingAdapter/LogicModelAdapter implementations can supply
    the providers. This fill function performs selection/checks, not training.
    """
    from .build_pipeline import edit_candidates, goal_candidates
    from .construction_candidates import attributed_feedback, evidence_order
    member(role, "fill role", ("build_goal", "build_optimizer"))
    session.check_goal()
    if session.logic is None:
        raise ContractError("stage 1 construction logic is required")
    if binding_provider is None:
        return {"status": "binding_provider_unavailable", "training_status": "engineering_untrained", "best_deck": None}
    task = session.task
    from .construction_progress import host_construction_quality, quality_policy as validate_quality_policy
    if quality_policy is None:
        from .effect_mechanisms import MechanismCatalog
        catalog = getattr(binding_provider, 'semantic_catalog', None) or MechanismCatalog(assets, task.pool)
        quality_policy = host_construction_quality(task, catalog=catalog)[0]
    quality_policy = validate_quality_policy(quality_policy)
    policy_sha = digest(quality_policy)
    cached = {}
    if pending_quality is not None:
        if (pending_quality.get('task_sha256') != task.sha256 or pending_quality.get('logic_sha256') != session.logic.sha256 or pending_quality.get('policy_sha256') != policy_sha):
            raise ContractError('pending quality batch belongs to another task/logic/policy')
        cached = {int(i): row for i, row in pending_quality['evaluations'].items()}
    feedback=attributed_feedback(session)
    axes = select_main_axes(task, assets, session.classification, scopes)
    if axes["status"] not in ("selected", "skipped_broad"):
        return {"status": axes["status"], "stage_2": axes, "best_deck": None}
    if role == "build_optimizer" and base is None:
        raise ContractError("optimizer filling requires an existing concrete deck")
    generation_trace = {}
    query_options = {}
    def model_scores(batch):
        import torch
        model = models[role]
        was_training = model.training
        try:
            model.eval()
            with torch.no_grad():
                return model(batch).tolist()
        finally:
            model.train(was_training)

    if models is not None:
        if encoder is None or role not in models:
            raise ContractError("existing role model and bound encoder required together")
        if pending_quality is None and hasattr(encoder, 'batch_inventories'):
            query_options['rank_ideas'] = lambda inventories: model_scores(encoder.batch_inventories(task, inventories))
    if pending_quality is None and recognition_mode == 'assist' and recognition_provider is not None and incumbent_recognition and base is not None:
        from .construction_recognition import recognized_mechanism_cards
        query_options['recognized_cards'] = recognized_mechanism_cards(incumbent_recognition, task, base)
    if pending_quality is None and len(task.pool) > 128:
        from .construction_retrieval import candidate_ids
        ids, retrieval = candidate_ids(task, assets, session.logic, base=base, scopes=scopes,
            cursor=query_cursor, limit=retrieval_limit,
            catalog=layer_adapter.catalog if layer_adapter is not None else None,
            theme_profile=quality_policy.get('quality',{}).get('theme_profile'))
        query_options['candidate_ids'] = ids
        generation_trace['retrieval'] = retrieval
    if pending_quality is None and scopes and layer_adapter is not None:
        from .build_semantics import matches as public_matches
        ids = query_options.get('candidate_ids', task.pool)
        core = [c for c in ids if any(public_matches(assets.rows[c], dict(field=s.field,value=s.value)) for s in scopes)]
        groups = layer_adapter.catalog.construction_mechanism_groups(ids, core)
        mechanism_groups = tuple(mechanism_groups or ()) + tuple(groups)
        generation_trace['mechanism_groups'] = list(groups)
    if pending_quality is not None:
        candidates = [{**row, 'deck': DeckParts.from_dict(row['deck'])}
                      for row in pending_quality['candidates']]
        generation_trace = pending_quality['generation']
    elif role == 'build_optimizer' and base is not None and not assets.accepts(task, base):
        assets.validate_skeleton(task, base)
        candidates = goal_candidates(task, assets, skeleton=base, return_portfolio=True,
                                    trace=generation_trace, **query_options)
        generation_trace['generator'] = 'optimizer_completion_of_goal_skeleton'
    else:
        candidates = (goal_candidates(task, assets, base,feedback=feedback,return_portfolio=True,mechanism_groups=mechanism_groups,trace=generation_trace,graph=session.logic,**query_options) if role == "build_goal"
                      else edit_candidates(task, assets, base, require_edit=False,feedback=feedback,return_portfolio=True,mechanism_groups=mechanism_groups,trace=generation_trace,graph=session.logic,search_offset=search_offset,**query_options))
    portfolio_rows=candidates
    candidates=[row["deck"] for row in portfolio_rows]
    from .construction_recognition import (collect_recognition, recognition_quality_evidence,
        recognition_evidence_validator, recognition_binding)
    recognition_records = collect_recognition(recognition_provider, recognition_mode, task, candidates, assets)
    recognition_identity = recognition_binding(recognition_provider, recognition_records, recognition_mode)
    compatible = pending_quality is not None and pending_quality.get('recognition_binding') == recognition_identity
    if not compatible:
        cached = {}
    scores, ranking = [0.] * len(candidates), "engineering_order_untrained"
    if pending_quality is not None:
        scores, ranking = list(pending_quality['scores']), pending_quality['ranking']
    elif models is not None:
        if candidates:
            scores = model_scores(encoder.batch(task, candidates))
            if len(scores) != len(candidates) or any(not math.isfinite(s) for s in scores):
                raise ContractError("invalid existing model candidate scores")
        ranking = "existing_role_model_uncalibrated"
    order = (list(pending_quality['order']) if pending_quality is not None else
             sorted(range(len(candidates)), key=lambda i: (-scores[i], i)))
    evaluation_order = list(order)
    from .construction_binding import CatalogBindingAdapter
    from .construction_layer_flow import ConstructionLayerAdapter
    if layer_adapter is None and isinstance(binding_provider, CatalogBindingAdapter):
        layer_adapter = ConstructionLayerAdapter(binding_provider)
    if layer_adapter is None:
        raise ContractError('functional quality requires the source-bound layer adapter')
    proposals, binding_errors, layer_evaluations = {}, {}, {}
    batch_basis = None
    def batch_state(evaluations, calculations, pending_indices, cursor, comparison_progress=None):
        nonlocal batch_basis
        if batch_basis is None:
            batch_basis = dict(version='functional-candidate-batch-v1', task_sha256=task.sha256,
                recognition_binding=recognition_identity, logic_sha256=session.logic.sha256, policy_sha256=policy_sha,
                candidates=[dict(row, deck=row['deck'].to_dict()) for row in portfolio_rows],
                proposals={str(i): dict(p.__dict__, deck=p.deck.to_dict(), connector_ids=list(p.connector_ids),
                    bindings=[{'node_id': b.node_id, 'card_ids': list(b.card_ids)} for b in p.bindings])
                    for i, p in proposals.items()},
                binding_errors=binding_errors, generation=generation_trace, order=evaluation_order,
                scores=scores, ranking=ranking)
        return dict(batch_basis,
            evaluations={str(i):row for i,row in evaluations.items()},
            calculation_progress={str(i):row for i,row in calculations.items()}, pending_indices=pending_indices,
            evaluation_cursor=cursor, comparison_progress=comparison_progress)
    layer_trace = {"status":"source_context_unavailable","pairs":[],"evaluated_indices":[]}
    comparisons = {}
    if layer_adapter is not None:
        if not isinstance(layer_adapter, ConstructionLayerAdapter) or layer_adapter.binding.assets is not assets:
            raise ContractError("layer adapter must use this fill's source assets")
        layer_logic = session.logic
        context = layer_adapter.context(task, layer_logic)
        limit = layer_adapter.limit(task, context)
        quality_evidence = recognition_quality_evidence(quality_evidence, recognition_provider, recognition_records,
            recognition_mode, validator=recognition_evidence_validator(layer_adapter, quality_policy, context))
        if pending_quality is not None:
            proposals = {int(i): FillProposal.from_dict(row) for i, row in pending_quality['proposals'].items()}
            binding_errors = {int(i): message for i, message in pending_quality['binding_errors'].items()}
        cursor = pending_quality.get('evaluation_cursor', 0) if compatible else 0
        schedule = order[cursor:] + order[:cursor]
        for index in [i for i in schedule if i not in cached and i not in binding_errors][:limit]:
            try:
                proposal = binding_provider(session.logic, task, candidates[index])
                if not isinstance(proposal, FillProposal) or proposal.deck != candidates[index]:
                    raise ContractError("binding provider must preserve the generated candidate and quantities")
                if proposal.task_sha256 != task.sha256 or proposal.logic_sha256 != session.logic.sha256:
                    raise ContractError("layer binding belongs to another task/logic revision")
                _check_bindings(session.logic, proposal)
                assets.validate(task, proposal.deck)
                proposals[index] = proposal
            except ContractError as error:
                binding_errors[index] = str(error)
        session.check_goal()
        if session.logic.sha256 != layer_logic.sha256:
            raise ContractError("logic changed during candidate layer preparation")
        active = [i for i in order if i not in binding_errors]
        scheduled = [i for i in schedule if i not in binding_errors]
        allowed = set([i for i in scheduled if i not in cached][:limit]) | set(cached)
        def evaluation_progress(evaluations,calculations):
            remaining=[i for i in active if i not in evaluations]
            next_candidate = next((i for i in scheduled if i not in evaluations), None)
            cursor = evaluation_order.index(next_candidate) if next_candidate is not None else len(evaluation_order)
            on_evaluation_progress(batch_state(evaluations,calculations,remaining,cursor))
        order, candidate_evaluations, layer_trace = layer_adapter.evaluate(
            task, layer_logic, portfolio_rows, {i: p for i, p in proposals.items() if i in allowed}, active, context,
            policy=quality_policy, quality_evidence=quality_evidence, should_stop=should_stop, evaluated=cached,
            calculations={int(i):value for i,value in pending_quality.get('calculation_progress',{}).items()} if compatible else None,
            comparison_progress=pending_quality.get('comparison_progress') if compatible else None,
            _comparisons=_comparisons, on_progress=evaluation_progress if on_evaluation_progress is not None else None,
            evaluation_cursor=active.index(scheduled[0]) if scheduled else 0)
        cursor = layer_trace['evaluation_cursor']
        layer_trace['evaluation_cursor'] = evaluation_order.index(active[cursor]) if cursor < len(active) else len(evaluation_order)
        order += [i for i in evaluation_order if i in binding_errors]
        layer_evaluations = {i: row['layer_evaluation'] for i, row in candidate_evaluations.items()}
        comparisons = layer_trace.pop("_comparisons", {})
        layer_trace.update(candidate_limit=limit, uncovered_indices=[i for i in range(len(candidates))
            if i not in proposals and i not in binding_errors], binding_failures=dict(binding_errors),
            upstream_generation_work=deepcopy(generation_trace))
    quality_evaluations = {i: row['quality_evaluation'] for i, row in candidate_evaluations.items()}
    preference = evidence_order(feedback,task.sha256,"deck")
    trace_rows = [{"candidate_index":i,"strategy":row["strategy"],"changes":deepcopy(row["changes"]),
        "recognition_inventory":row["deck"].to_dict(),
        "portfolio_admission":deepcopy(row.get("portfolio_admission")),
        "generation":deepcopy(row.get("generation")),"proposal_basis":row.get("proposal_basis","bounded_listing_or_single_edit"),
        "proposal_source":row.get("proposal_source"),"goal_preserved":row["goal_preserved"],
        "dependency_repair":deepcopy(row.get("dependency_repair")),
        "score_available":models is not None,"model_score_uncalibrated":scores[i] if models is not None else None,
        "whole_candidate_evidence_order":preference.get(row["deck_sha256"],0),
        "layer_evaluation":layer_evaluations.get(i),
        "quality_evaluation_id":quality_evaluations.get(i,{}).get('evaluation_id'),
        "quality_summary":_quality_summary(quality_evaluations.get(i)),
        "evaluation_status":candidate_evaluations.get(i, {}).get('evaluation_status', 'deferred'),
        "layer_status":"evaluated" if i in layer_evaluations else "binding_unmatched" if i in binding_errors else layer_trace["status"] if layer_adapter is None else "budget_uncovered",
        "selection_order_position":order.index(i),"status":"not_attempted","retained":False,"selected":False}
        for i,row in enumerate(portfolio_rows)]
    candidate_trace = {"generation":generation_trace,"ranking":ranking,"calibration_status":"uncalibrated" if models is not None else "no_model_score",
        "score_interpretation":"whole_candidate_score_not_card_credit_or_win_rate",
        "target_constraints":{"goal":deepcopy(task.goal),"sizes":deepcopy(task.sizes),"requirements":deepcopy(task.requirements),"theme_axes":deepcopy(axes)},
        "order_rule":"final_effective_score_then_stable_model_order",
        "layers":layer_trace,
        "selection_rule":"first_task_valid_in_final_score_order","candidate_order":order,"candidates":trace_rows,
        "retained_limit":1,"selected_candidate_index":None,"selected_attempt_index":None,
        "strength_status":"unknown"}
    if recognition_records:
        candidate_trace['recognition'] = dict(mode=recognition_mode, records=recognition_records)
    batch=batch_state(candidate_evaluations,layer_trace.get('calculation_progress',{}),
        layer_trace['pending_indices'],layer_trace['evaluation_cursor'],layer_trace.pop('comparison_progress'))
    if not layer_trace['selection_complete']:
        pending=batch
        return dict(status='quality_evaluation_pending', best_deck=None, attempts=[], portfolio=[],
            learning_candidates=[], candidate_trace=candidate_trace, pending_quality=pending,
            pending_candidates=[deepcopy(pending['candidates'][i]) for i in pending['pending_indices']],
            evaluation_cursor=pending['evaluation_cursor'], selection_complete=False,
            graph_execution_verified=False)
    results, retained, selected = [], [], None
    for index in order:
        attempt_index = len(results)
        item = trace_rows[index]
        item["attempt_index"] = attempt_index
        try:
            if index in binding_errors:
                raise ContractError(binding_errors[index])
            proposal = proposals[index] if index in proposals else binding_provider(session.logic, task, candidates[index])
        except ContractError as error:
            session.record_feedback("fill", "graph binding failed: " + str(error))
            results.append({"status":"binding_unmatched","unmet":[str(error)],"best_deck":None,
                "candidate_index":index,"ranking":ranking,"model_score_uncalibrated":item["model_score_uncalibrated"]})
            item.update(status="binding_unmatched",unmet=[str(error)])
            continue
        if not isinstance(proposal, FillProposal) or proposal.deck != candidates[index]:
            raise ContractError("binding provider must preserve the generated candidate and quantities")
        result = evaluate_fill(session, assets, proposal, scopes=scopes, text_reviewer=text_reviewer, verifier=verifier, defer_engine=defer_engine)
        result.update(role=role, ranking=ranking, candidate_index=index, model_score_uncalibrated=item["model_score_uncalibrated"],
            layer_candidate_index=index, layer_status=item["layer_status"])
        results.append(result)
        item.update(status=result["status"],unmet=deepcopy(result.get("unmet",[])),card_list_legal=result.get("card_list_legal"),
            public_effect_evidence={"text_reviews_attempt_index":attempt_index,
                "bindings":[{"node_id":b.node_id,"card_ids":list(b.card_ids)} for b in proposal.bindings],
                "reviewed_card_ids":sorted({e["card_id"] for review in result.get("text_reviews",[]) for e in review["evidence"]}),
                "interpretation":"source_bound_card_effect_assessment_not_model_score_attribution"})
        if result["status"] in ("task_goal_verified_logic_unproven", "list_constraints_verified_logic_unproven", "concrete_candidate_cb_pending"):
            item["retained"] = True
            if selected is None:
                selected=len(results)-1; item["selected"]=True
                candidate_trace.update(selected_candidate_index=index,selected_attempt_index=selected)
            row=portfolio_rows[index]
            retained.append({"deck":candidates[index].to_dict(),"logic":session.logic.to_dict(),
                **({'recognition':deepcopy(recognition_records.get(digest(candidates[index].to_dict())))} if recognition_records else {}),
                "logic_sha256":session.logic.sha256,"goal_sha256":session.goal_sha256,
                "candidate_index":index,"attempt_index":attempt_index,"generation":deepcopy(row.get("generation")),
                "strategy":row["strategy"],"changes":row["changes"],
                "proposal_basis":row.get("proposal_basis","bounded_listing_or_single_edit"),
                "proposal_source":row.get("proposal_source"),
                "protected_package":deepcopy(row.get("protected_package")),
                "layer_evaluation":layer_evaluations.get(index),
                "quality_evaluation":quality_evaluations.get(index),
                "evaluation_status":candidate_evaluations.get(index, {}).get('evaluation_status'),
                "model_score_uncalibrated":item["model_score_uncalibrated"],"strength_status":"unknown",
                "concrete_proposal":result.get("concrete_proposal")})
            break
    if selected is not None:
        best=results[selected]
        chosen = best["candidate_index"]
        # Detailed changes are relative to the actual accepted choice, which
        # can differ from the first ranked option after text/list validation.
        for item in trace_rows:
            other = item["candidate_index"]
            pair = (chosen, other) if (chosen, other) in comparisons else (other, chosen)
            item["comparison_with_selected"] = (None if other == chosen else
                {"before_candidate_index":pair[0], "after_candidate_index":pair[1], **comparisons[pair]}
                if pair in comparisons else None)
        for row in retained:
            row["quality_comparison"] = trace_rows[row["candidate_index"]]["comparison_with_selected"]
            row["quality_comparisons"] = [v for pair,v in comparisons.items() if row["candidate_index"] in pair]
        selection_reason = {"rule":candidate_trace["order_rule"], "candidate_index":chosen,
            "unresolved_or_equal_pairs":[p for p in layer_trace["pairs"] if chosen in (p["before"],p["after"])
                and p["status"] != "preferred"],
            "preferred_pairs":[p for p in layer_trace["pairs"] if p["preferred_index"] == chosen]}
        candidate_trace["selection_reason"] = selection_reason
        # The round consumes these evaluations before saving its compact receipt.
        learning_candidates = [{"deck":candidates[i].to_dict(),"layer_evaluation":layer_evaluations[i],
            **({'quality_evaluation':quality_evaluations[i], 'evaluation_status':candidate_evaluations[i]['evaluation_status']}),
            "quality_comparisons":[v for pair,v in comparisons.items() if i in pair]}
            for i in proposals if i in layer_evaluations]
        return {"status":best["status"],"best_deck":best["best_deck"],"attempts":results,
                "_evaluation_batch":batch,
                "selected_attempt_index":selected,"portfolio":retained,
                "learning_candidates":learning_candidates,
                "quality_evaluation":quality_evaluations.get(chosen),
                "quality_comparisons":list(comparisons.values()),
                "selection_complete":True, "pending_candidates":[], "pending_quality":None,
                "layer_evaluation":layer_evaluations.get(chosen), "layer_selection":selection_reason,
                "ranking":ranking,"candidate_trace":candidate_trace,"graph_execution_verified":False}
    return {"status": "no_verified_fill_within_candidates", "best_deck": results[-1]["best_deck"] if results else None,
            "attempts": results, "ranking": ranking,"candidate_trace":candidate_trace,
            "returned_deck_source":"last_attempt_or_its_prior_fallback" if results else "none", "graph_execution_verified": False}


def construct_task(task,assets,models,encoder,*,base=None,lora_versions=None, continuation=None, **iteration_options):
    """Shared role-separated entry; callers persist the returned session."""
    from types import SimpleNamespace
    from .autonomous_construction import _SharedLogicAdapter
    from .build_intent import IntentClassification
    from .construction_binding import CatalogBindingAdapter,PublicFactTag
    from .construction_effect_blocks import logic_vocabulary, requested_logic_tags
    from .construction_layer_flow import ConstructionLayerAdapter
    from .construction_logic import ConstructionSession, ThemeScope, declared_theme_scopes
    from .construction_model import LogicCodec
    tags = logic_vocabulary()
    declared = declared_theme_scopes(task)
    scopes = iteration_options.pop('scopes',declared)
    if (not isinstance(scopes,tuple) or any(not isinstance(s,ThemeScope) for s in scopes) or
            {(s.field,s.value) for s in scopes}!={(s.field,s.value) for s in declared}):
        raise ContractError('fixed-task theme scopes must preserve its declared series/race requirements')
    facts = tuple(PublicFactTag(LogicTag('field' if s.field=='setcode' else 'race',s.term),
        s.field,s.value,s.source) for s in scopes)
    scope_request = ' scopes '+digest([asdict(s) for s in scopes]) if scopes else ''
    session=ConstructionSession('Explicit fixed construction task '+task.task_id+scope_request,task)
    session.classification=IntentClassification('narrow' if scopes else 'broad',1.,tuple(s.term for s in scopes),
        reasons=('explicit fixed-task series/race requirements' if scopes else 'explicit fixed task',))
    adapter=_SharedLogicAdapter(task,SimpleNamespace(models=models,encoder=encoder),
        LogicCodec((*tags,*(f.tag for f in facts)),('ns','ss','送墓时发动')),{r:0 for r in models},
        required_tags=requested_logic_tags(task,tuple(f.tag for f in facts)))
    binding=CatalogBindingAdapter(assets,fact_tags=facts)
    if continuation is not None:
        from .construction_logic import ConstructionLogic
        from .construction_progress import restore_progress
        if continuation['task'] != task.to_dict() or continuation['goal_sha256'] != session.goal_sha256:
            raise ContractError('fixed-task continuation belongs to another request')
        session.logic = ConstructionLogic.from_dict(continuation['logic']) if continuation['logic'] else None
        session.history = deepcopy(continuation['history'])
        session.feedback = deepcopy(continuation['feedback'])
        session.optimization_feedback = deepcopy(continuation.get('optimization_feedback', []))
        restore_progress(session, continuation.get('construction_progress'), assets)
    result=construction_cycle(session,assets,adapter.providers(),base=base,models=models,encoder=encoder,
        scopes=scopes,
        binding_provider=binding,text_reviewer=binding.reviewer,verifier=existing_goal_verifier,
        layer_adapter=ConstructionLayerAdapter(binding), **iteration_options)
    stages = [dict(stage=i, role=phase['role'], deck_sha256=phase['proposal_deck_sha256'],
                   quality_summary=phase.get('quality_summary'), lora_version=(lora_versions or {}).get(phase['role']))
              for i, phase in enumerate(result['phases']) if 'proposal_deck_sha256' in phase]
    return dict(result,stages=stages,best_deck=result['best']['deck'] if result['best'] else None,
        best_criterion='versioned_pre_cb_construction_gate',task_sha256=task.sha256, session=session.to_dict())


def _candidate_basic_cb(task,deck,assets,provider,gate=None,recognition_record=None):
    subject=digest(deck.to_dict())
    if provider is None:
        result={"kind":"basic_cb_inference_after_construction","status":"not_run","routes":[],
                "inference_completed":False,"unknown_is_not_negative":True}
    else:
        from .construction_recognition import cb_search_hints
        hints = cb_search_hints(recognition_record or {})
        options = {'recognition_hints': deepcopy(hints)} if hints is not None and getattr(provider, 'accepts_recognition_hints', False) is True else {}
        result=deepcopy(provider(task,deck,assets,construction_gate=deepcopy(gate),**options))
        if not isinstance(result,dict) or not isinstance(result.get("status"),str):
            raise ContractError("basic CB provider must return a scoped inference result")
    if (result.get("subject_deck_sha256",subject)!=subject or result.get("task_sha256",task.sha256)!=task.sha256):
        raise ContractError("basic CB result belongs to a different task/deck")
    result.update(subject_deck_sha256=subject,task_sha256=task.sha256,
                  inference_scope="basic_cb_for_constructed_deck_not_whole_graph_acceptance")
    return result


def _deficiencies(quality, *, limit=4):
    """Explained losses for feedback; final score alone determines ranking."""
    return [dict(item='functional', key=row['stage'], value=row['lower'], basis='effective_inputs')
            for row in quality['losses'] if row['lower'] > 0][:limit]


def _quality_summary(quality):
    if quality is None:
        return None
    from .construction_learning import _current_quality
    _current_quality(quality)
    total = quality['total']
    return dict(status=total['status'], value=total['value'], min=total['min'], max=total['max'],
        complete=total['complete'], scope_complete=total['scope_complete'],
        policy_version=quality['policy_version'],
        deferred=list(total['deferred']), unknown_items=list(total['unknown_items']),
        partial_items=list(total['partial_items']), unit=total['unit'],
        evaluation_id=quality['evaluation_id'], top_deficiencies=_deficiencies(quality))


def _gate_feedback(gate, quality):
    text = ('Construction gate: ' + '; '.join(gate['reasons']))[:512] if gate['reasons'] \
        else 'Construction gate passed for current candidate'
    summary = _quality_summary(quality)
    if summary is not None:
        if summary['value'] is not None:
            text += ' | quality %.2f' % summary['value']
        else:
            text += ' | quality %s..%s (incomplete)' % (summary['min'], summary['max'] if summary['max'] is not None else 'unknown')
            gap_items = summary['unknown_items'] + summary['partial_items']
            if gap_items:
                text += ' unknown: ' + ','.join(gap_items)
        if summary['deferred']:
            text += ' | deferred: ' + ','.join(summary['deferred'])
        if summary['top_deficiencies']:
            text += ' | deficits: ' + ', '.join('%s/%s=%s' % (row['item'], row['key'], row['value'])
                for row in summary['top_deficiencies'])
    return text[:1024]


def _construction_cycle(session, assets, providers, *, scopes=(), base=None, models=None, encoder=None,
                       binding_provider=None, text_reviewer=None, verifier=existing_goal_verifier,
                       basic_cb_provider=None, mechanism_groups=None, layer_adapter=None,
                       quality_criteria=None, quality_evidence=None, quality_reference=None, max_iterations=4, seconds=None,
                       max_candidates=None, pause_requested=None, cb_authorized=False,
                       recognition_provider=None, recognition_mode="off", quality_factory=None, retrieval_limit=128,
                       _validate_saved=True, _comparisons=None):
    """Goal skeleton once, then optimizer slices until the pre-CB gate passes."""
    import time
    from .build_pipeline import candidate_limit
    from .construction_candidates import changes
    from .construction_progress import (compact_completed_progress, compact_optimizer_phase,
        construction_gate, quality_policy, restore_progress, feedback_for_iteration,
        finish_feedback, record_reference_attempt, invalidate_reference_evaluation, REFERENCE_STAGE_VERSION)
    from .validation import integer
    integer(max_iterations, 'optimizer iterations per slice', 0, 64)
    if seconds is not None and (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0):
        raise ContractError('construction time slice must be None or finite nonnegative seconds')
    if type(cb_authorized) is not bool:
        raise ContractError('explicit CB execution authorization required')
    if quality_evidence is not None and not callable(quality_evidence):
        raise ContractError('quality evidence provider must be callable')
    round_limit = candidate_limit(session.task)
    max_candidates = max_candidates if max_candidates is not None else max_iterations * round_limit
    integer(max_candidates, 'construction candidates per slice', 0)
    derive_policy = quality_criteria is None
    policy = quality_policy(quality_criteria)
    session.check_goal()
    state = session.construction_progress
    if state is not None:
        if _validate_saved:
            restore_progress(session, state, assets, policy=policy, _comparisons=_comparisons)
        state = dict(session.construction_progress)
        if policy is not None and state['quality_policy'] is None:
            state.update(quality_policy=policy, status='optimizing')
        elif policy is not None and policy != state['quality_policy']:
            if (policy['version'] == 'construction-host-functional-v2'
                    and policy.get('quality', {}).get('theme_profile', {}).get('task_sha256') == session.task.sha256):
                from .construction_progress import revise_quality_policy
                revise_quality_policy(session, policy)
                state = dict(session.construction_progress)
            else:
                raise ContractError('quality policy changed during a bound construction; explicitly revise the policy')
        policy = state['quality_policy']
    elif base is not None:
        assets.validate(session.task, base)
    phases, spent = [], 0
    started = time.monotonic()
    reason = 'iteration_slice_exhausted'
    def stopped():
        if pause_requested is not None and pause_requested():
            return 'user_pause'
        if seconds is not None and time.monotonic() - started >= seconds:
            return 'time_slice_exhausted'
        return None
    def save():
        state['logic_sha256'] = session.logic.sha256
        session.construction_progress = dict(state)
    def graph_selection(role):
        owner = getattr(providers.get(role), '__self__', None)
        return deepcopy(getattr(owner, 'last_selection', {}).get(role))
    if state is None and stopped() is None:
        phase = dict(phase_number=1, role='build_goal', input_deck=None,
            parameter_update_performed=False, responsibility='axis_skeleton')
        phases.append(phase)
        phase['stage_1'] = session.propose_logic('build_goal', providers.get('build_goal'))
        phase['graph_model_selection'] = graph_selection('build_goal')
        phase['stage_2'] = (select_main_axes(session.task,assets,session.classification,scopes)
            if phase['stage_1']['status']=='logic_revised' else dict(status='not_run',axes=[]))
        if phase['stage_1']['status'] == 'logic_revised':
            result = build_axis_skeleton(session, assets, models=models, encoder=encoder,
                binding_provider=binding_provider, text_reviewer=text_reviewer, scopes=scopes, layer_adapter=layer_adapter,
                recognition_provider=recognition_provider, recognition_mode=recognition_mode)
            phase['stage_3'] = result
            if result['status'] == 'axis_skeleton_ready':
                deck = DeckParts.from_dict(result['best_deck'])
                row = dict(deck=deck.to_dict(), deck_sha256=digest(deck.to_dict()),
                    concrete_proposal=result['concrete_proposal'], layer_evaluation=None)
                phase.update(proposal_deck=deck.to_dict(), proposal_changes=changes(DeckParts((),(),()), deck),
                    unfilled=result['unfilled'], acceptance='axis_skeleton_handoff')
                state = dict(schema_version=3, task_sha256=session.task.sha256, status='optimizing',
                    logic_sha256=session.logic.sha256, candidate=row, skeleton=deepcopy(row),
                    candidate_version=1, iteration=0, candidate_cursor=0, query_cursor=0, stagnation=0,
                    quality_policy=policy, gate=None, retained_candidates=[], last_optimizer_phase=None)
                state.update(pending_quality=None, pending_phase=None, pending_reference=None,
                    reference_evaluation=None, reference_binding=None)
                state['handoffs'] = [dict(role='build_goal', candidate_version=1,
                    input_deck_sha256=None, output_deck_sha256=row['deck_sha256'])]
                save()
        if state is None:
            reason = 'axis_skeleton_unresolved'
    if state is not None and (derive_policy or quality_factory is not None):
        if quality_factory is None:
            from .construction_progress import host_construction_quality
            from .effect_mechanisms import MechanismCatalog
            catalog = layer_adapter.catalog if layer_adapter is not None else MechanismCatalog(assets, session.task.pool)
            quality_criteria, default_reference = host_construction_quality(session.task, catalog=catalog,
                period_id=(getattr(assets, 'period_context', None) or {}).get('period_id'))
        else:
            quality_criteria, default_reference = quality_factory()
        policy = quality_policy(quality_criteria)
        if quality_reference is None:
            quality_reference = default_reference
        if state.get('quality_policy') is not None and state['quality_policy'] != policy:
            from .construction_progress import revise_quality_policy
            revise_quality_policy(session, policy)
            state = dict(session.construction_progress)
        state['quality_policy'] = policy
        save()
    if state is not None:
        if quality_reference is None:
            quality_reference = deepcopy(state.get('quality_reference'))
        else:
            state['quality_reference'] = deepcopy(quality_reference)
    reference_adapter = layer_adapter
    def prepare_reference():
        nonlocal reference_adapter
        if reference_adapter is None:
            from .construction_binding import CatalogBindingAdapter
            from .construction_layer_flow import ConstructionLayerAdapter
            reference_adapter = ConstructionLayerAdapter(CatalogBindingAdapter(assets))
        completed_binding = state.get('reference_binding') if state.get('reference_evaluation') is not None else None
        return reference_adapter.reference_inputs(session.task, session.logic, quality_reference,
            policy['pass']['reference'], policy=policy, quality_evidence=quality_evidence,
            completed_binding=completed_binding)

    if (state and state['status'] == 'passed' and policy and policy['pass']['mode'] == 'reference_ratio'
            and stopped() is None):
        try:
            _, binding, _ = prepare_reference()
        except ContractError:
            binding = None
        if binding is None or binding != state.get('reference_binding'):
            invalidate_reference_evaluation(state)
            state.update(status='optimizing', gate=None)
            save()
    for _ in range(max_iterations if state else 0):
        if policy is None:
            reason = 'quality_policy_unconfigured'
            break
        if state['status'] == 'passed' and not any(r['status'] == 'pending' for r in session.optimization_feedback):
            break
        reference_stage = state.get('pending_reference')
        resuming = bool(state.get('pending_quality') or reference_stage)
        reason = stopped() or ('candidate_slice_exhausted' if not resuming and spent + round_limit > max_candidates else '')
        if reason:
            break
        current = DeckParts.from_dict(state['candidate']['deck'])
        state['status'] = 'optimizing'
        iteration = state['iteration'] + 1
        if resuming:
            phase = dict(state['pending_phase'])
            packages = []
            receipts = [r for r in session.optimization_feedback
                        if r['status'] == 'consumed_pending_assessment' and r['consumed_iteration'] == iteration]
        else:
            messages, packages, receipts = feedback_for_iteration(session, current, iteration)
            for item in messages:
                session.record_feedback(item['source'], item['message'])
            phase = dict(phase_number=iteration+1, role='build_optimizer', optimization_iteration=iteration,
                input_deck=current.to_dict(), input_candidate_version=state['candidate_version'],
                feedback_before=deepcopy(session.feedback), optimization_feedback=deepcopy(receipts),
                parameter_update_performed=False, responsibility='relations_quantities_and_generic_slots')
            phase['stage_1'] = session.propose_logic('build_optimizer', providers.get('build_optimizer'))
            phase['graph_model_selection'] = graph_selection('build_optimizer')
            phase['stage_2'] = (select_main_axes(session.task,assets,session.classification,scopes)
                if phase['stage_1']['status']=='logic_revised' else dict(status='not_run',axes=[]))
        phases.append(phase)
        if phase['stage_1']['status'] != 'logic_revised':
            finish_feedback(receipts, None)
            reason = 'optimizer_logic_unresolved'
            break
        if reference_stage is not None:
            result = phase['stage_3']
        else:
            generation_recorded = False
            def save_evaluation_progress(batch):
                nonlocal spent, generation_recorded
                if not resuming and not generation_recorded:
                    generated = len(batch['candidates'])
                    spent += generated
                    state['candidate_cursor'] += max(1, generated)
                    retrieval = batch.get('generation', {}).get('retrieval', {})
                    state['query_cursor'] = retrieval.get('next_cursor', state.get('query_cursor', 0))
                    generation_recorded = True
                state.update(pending_quality=batch, pending_phase={k: v for k, v in phase.items() if k != 'stage_3'})
                save()
            result = fill_with_existing(session, assets, role='build_optimizer', base=current,
                models=models, encoder=encoder, binding_provider=binding_provider, text_reviewer=text_reviewer,
                scopes=scopes, verifier=None, defer_engine=True,
                mechanism_groups=tuple(packages) + tuple(mechanism_groups or ()), layer_adapter=layer_adapter,
                search_offset=state['candidate_cursor'], quality_policy=policy,
                quality_evidence=quality_evidence,
                should_stop=stopped, pending_quality=state.get('pending_quality'),
                query_cursor=state.get('query_cursor',0), retrieval_limit=retrieval_limit,
                on_evaluation_progress=save_evaluation_progress,
                incumbent_recognition=state['candidate'].get('recognition'), recognition_provider=recognition_provider, recognition_mode=recognition_mode,
                _comparisons=_comparisons)
            phase['stage_3'] = result
            generated = len(result.get('candidate_trace', {}).get('candidates', ()))
            if not resuming and not generation_recorded:
                spent += generated
                state['candidate_cursor'] += max(1, generated)
                retrieval = result.get('candidate_trace', {}).get('generation', {}).get('retrieval', {})
                state['query_cursor'] = retrieval.get('next_cursor', state.get('query_cursor', 0))
            if result['status'] == 'quality_evaluation_pending':
                state.update(pending_quality=result['pending_quality'],
                    pending_phase={k: v for k, v in phase.items() if k != 'stage_3'})
                reason = result['candidate_trace']['layers'].get('stop_reason') or 'quality_evaluation_budget'
                save()
                break
            batch = result.pop('_evaluation_batch', None)
            if result['status'] != 'concrete_candidate_cb_pending':
                state.update(pending_quality=None, pending_phase=None, pending_reference=None)
                finish_feedback(receipts, None)
                reason = 'no_valid_optimizer_candidate'
                save()
                break
            if policy['pass']['mode'] == 'reference_ratio':
                batch = dict(batch, evaluations={}, calculation_progress={},
                    pending_indices=list(batch['order']), evaluation_cursor=0)
                reference_stage = dict(version=REFERENCE_STAGE_VERSION, candidate_batch=batch,
                    binding=None, calculation=None)
                state.update(pending_quality=None, pending_phase=phase, pending_reference=reference_stage)
                save()
            elif stopped() == 'user_pause':
                state.update(pending_quality=batch, pending_phase={k: v for k, v in phase.items() if k != 'stage_3'})
                break
        if stopped() == 'user_pause':
            break
        row = dict(next(r for r in result['portfolio'] if r['deck'] == result['best_deck']))
        deck = DeckParts.from_dict(row['deck'])
        if reference_stage is not None:
            state['reference_error'] = None
            try:
                reference_deck, binding, inputs = prepare_reference()
                if state.get('reference_evaluation') is None or state.get('reference_binding') != binding:
                    invalidate_reference_evaluation(state)
                    calculation = (reference_stage['calculation']
                                   if reference_stage['binding'] == binding else None)
                    reference, work, stop = reference_adapter.evaluate_inventory(session.task, reference_deck,
                        **inputs, should_stop=stopped, calculation=calculation)
                    if work is not None:
                        state['pending_reference'] = dict(reference_stage, binding=binding, calculation=work)
                        reason = stop or 'reference_calculation_budget'
                        save()
                        break
                    state.update(reference_evaluation=reference, reference_binding=binding)
            except ContractError as error:
                invalidate_reference_evaluation(state)
                state['reference_error'] = str(error)
            if stopped() == 'user_pause':
                break
        reference = state.get('reference_evaluation')
        if reference_stage is not None and reference is not None:
            ratio = policy['pass']['minimum_reference_ratio']
            chosen_id = row['quality_evaluation']['evaluation_id']
            trace_by_id = {item['quality_evaluation_id']: item for item in result['candidate_trace']['candidates']}
            for item in result.get('learning_candidates', ()):
                quality = item['quality_evaluation']
                identity = quality['evaluation_id']
                if identity != chosen_id:
                    trace_by_id[identity]['reference_delta'] = _comparisons.delta(reference, quality, ratio)
        state.update(pending_quality=None,pending_phase=None,pending_reference=None)
        state['iteration']=iteration
        row['deck_sha256'] = digest(row['deck'])
        state['stagnation'] = state['stagnation'] + 1 if deck == current else 0
        state['candidate_version'] += 1
        gate = construction_gate(session.task, deck, assets, row.get('layer_evaluation'),
            policy=policy, candidate_version=state['candidate_version'], quality=row['quality_evaluation'],
            reference_quality=reference, _comparisons=_comparisons,
            _reference_validated=reference_stage is not None and reference is not None)
        if state.get('reference_error'):
            gate['reasons'].append('reference_invalid:'+state['reference_error'])
        reference_hint = record_reference_attempt(state, gate)
        finish_feedback(receipts, deck)
        phase.update(proposal_deck=deck.to_dict(), proposal_changes=changes(current, deck),
            output_candidate_version=state['candidate_version'], gate=gate,
            quality_summary=_quality_summary(row['quality_evaluation']),
            reference_feedback=deepcopy(state.get('reference_feedback')),
            optimization_feedback=deepcopy(receipts), acceptance='passed' if gate['status'] == 'passed' else 'working_candidate_only')
        phase = compact_optimizer_phase(phase, task=session.task, _comparisons=_comparisons)
        phases[-1] = phase
        state.update(candidate=row, gate=gate, retained_candidates=[],
            status='passed' if gate['status'] == 'passed' else 'optimizing', last_optimizer_phase=phase)
        compact_completed_progress(state)
        _comparisons.release_candidates(row['quality_evaluation'], reference)
        state['handoffs'] = [*state['handoffs'], dict(role='build_optimizer', candidate_version=state['candidate_version'],
            input_deck_sha256=digest(current.to_dict()), output_deck_sha256=row['deck_sha256'])]
        save()
        session.history.append(dict(stage='construction_iteration', role='build_optimizer',
            iteration=iteration, candidate_version=state['candidate_version'], deck_sha256=row['deck_sha256'],
            gate=deepcopy(gate), quality_summary=_quality_summary(row['quality_evaluation']),
            parameter_update_performed=False))
        message = _gate_feedback(gate, row['quality_evaluation'])
        if reference_hint:
            message = reference_hint['message'] + ' | ' + message
        session.record_feedback('coordinator', message[:1024])
        reason = 'iteration_slice_exhausted'
    passed = bool(state and state['status'] == 'passed')
    stop = stopped()
    user_stopped = stop == 'user_pause'
    reason = 'user_pause' if user_stopped else 'construction_passed' if passed else stop or reason or 'iteration_slice_exhausted'
    if state:
        state.update(status='passed' if passed else 'suspended', stop_reason=reason)
        save()
    candidate = dict(state['candidate']) if state else None
    cb, cb_optimize = None, False
    def finalize(row, gate):
        deck = DeckParts.from_dict(row['deck'])
        allowed = gate['status'] == 'passed' and cb_authorized and stopped() is None
        inference = _candidate_basic_cb(session.task, deck, assets, basic_cb_provider if allowed else None, gate,
                                       row.get('recognition') if recognition_mode == 'assist' else None)
        inference.update(construction_gate=deepcopy(gate), candidate_version=gate['candidate_version'],
            execution_authorized=allowed)
        checked = False
        validation = {'status': 'construction_pending', 'best_deck': None, 'attempts': []}
        if gate['status'] == 'passed':
            static = session.task.goal['kind'] == 'deck_constraints' and 'route_goal' not in session.task.goal
            if static:
                from .build_semantics import proof
                checked = True
                validation = dict(status='list_constraints_verified_logic_unproven', best_deck=row['deck'],
                    attempts=[{'engine_validation':proof(session.task,deck,assets)}])
            elif allowed and verifier is not None:
                proof = evaluate_fill(session, assets, FillProposal.from_dict(row['concrete_proposal']),
                    scopes=scopes, text_reviewer=text_reviewer, verifier=verifier)
                checked = proof['status'] == 'task_goal_verified_logic_unproven'
                validation = dict(status=proof['status'], best_deck=row['deck'] if checked else None, attempts=[proof])
        return dict(row, construction_gate=deepcopy(gate), candidate_version=gate['candidate_version'],
            validation=validation, task_verified=checked, basic_cb=inference,
            cb_verified=inference.get('status') == 'routes_inferred' and bool(inference.get('routes')))
    if passed and not user_stopped:
        from .construction_progress import record_basic_cb_attempt, record_optimization_feedback
        cb_optimize = False
        for _ in range(2):
            candidate = finalize(candidate, state['gate'])
            cb = candidate['basic_cb']
            cb_optimize = record_basic_cb_attempt(state, cb)
            if (cb_optimize or cb.get('failure_count_eligible') is not True
                    or not cb_authorized or stopped() is not None):
                break
        if cb_optimize:
            record_optimization_feedback(session,dict(
                feedback_id='basic-cb-two-failures-'+str(state['candidate_version']),source='coordinator',
                task_sha256=session.task.sha256,candidate_sha256=state['candidate']['deck_sha256'],
                issue='基础CB连续两次正常完成仍无有效路线，重新检查启动、配套和路线条件。'))
            reason = 'basic_cb_requires_optimization'
            state.update(status='suspended',stop_reason=reason)
        save()
        if cb_optimize:
            used_iterations = sum(p['role']=='build_optimizer' for p in phases)
            remaining = None if seconds is None else seconds-(time.monotonic()-started)
            if ((remaining is None or remaining > 0) and used_iterations < max_iterations and
                    max_candidates-spent >= round_limit and stopped() is None):
                session.history.append(dict(stage='basic_cb_return_to_optimizer',
                    candidate_version=state['candidate_version'],deck_sha256=state['candidate']['deck_sha256']))
                following = _construction_cycle(session,assets,providers,scopes=scopes,base=base,
                    models=models,encoder=encoder,binding_provider=binding_provider,text_reviewer=text_reviewer,
                    verifier=verifier,basic_cb_provider=basic_cb_provider,mechanism_groups=mechanism_groups,
                    layer_adapter=layer_adapter,quality_criteria=policy,quality_evidence=quality_evidence,
                    quality_reference=quality_reference,max_iterations=max_iterations-used_iterations,seconds=remaining,
                    max_candidates=max_candidates-spent,pause_requested=pause_requested,cb_authorized=cb_authorized,
                    recognition_provider=recognition_provider, recognition_mode=recognition_mode,
                    retrieval_limit=retrieval_limit, _validate_saved=False, _comparisons=_comparisons)
                following['phases'] = phases + following['phases']
                return following
    elif candidate is not None:
        cb = _candidate_basic_cb(session.task, DeckParts.from_dict(candidate['deck']), assets, None)
        cb.update(execution_authorized=False,candidate_version=state['candidate_version'],construction_gate=deepcopy(state['gate']))
        candidate.update(basic_cb=cb,cb_verified=False,task_verified=False,
            construction_gate=deepcopy(state['gate']), validation={'status':'construction_pending','best_deck':None,'attempts':[]})
    admitted = passed and not cb_optimize and not user_stopped
    return dict(status='construction_passed' if admitted else 'construction_suspended', stop_reason=reason,
        phases=phases, best=candidate if admitted else None, verified_best=candidate if admitted and candidate['task_verified'] else None,
        basic_cb_optimization_requested=bool(passed and cb_optimize),
        construction_candidate=candidate, construction_passed=admitted, static_gate_passed=passed,
        construction_gate=deepcopy(state['gate']) if state else None,
        continuation=state, basic_cb=cb, retained_candidates=[],
        handoffs=deepcopy(state['handoffs']) if state else [],
        task_verified=bool(passed and candidate['task_verified']), cb_verified=bool(passed and candidate['cb_verified']),
        latest_logic_sha256=session.logic.sha256 if session.logic else None, goal_sha256=session.goal_sha256,
        task_goal_sha256=digest(session.task.goal), graph_execution_verified=False,
        deployment_incumbent={'deck_sha256':digest(base.to_dict()), 'new_cb_claimed':False} if base else None,
        optimization_feedback=deepcopy(session.optimization_feedback),
        stagnation={'rounds_without_inventory_change':state['stagnation'] if state else 0,
            'unresolved':state['gate']['reasons'] if state and state['gate'] else [reason],
            'next_action':'continue_optimizer_with_advanced_candidate_cursor'},
        optimization_training='no_parameter_update_in_construction_cycle', training_status='no_training_performed_by_this_cycle')


def build_axis_skeleton(session, assets, *, recognition_provider=None, recognition_mode="off", **options):
    from .construction_recognition import record_recognition_result, recognition_mode as check_mode
    check_mode(recognition_mode)
    result = _build_axis_skeleton(session, assets, **options)
    return record_recognition_result(result, session.task, assets, recognition_provider, recognition_mode)


def fill_with_existing(session, assets, *, recognition_provider=None, recognition_mode="off", **options):
    from .construction_recognition import record_recognition_result, recognition_mode as check_mode
    check_mode(recognition_mode)
    # Observations occur after all selections and learning inputs are frozen.
    result = _fill_with_existing(session, assets, recognition_provider=recognition_provider if recognition_mode == 'assist' else None,
                                 recognition_mode='assist' if recognition_mode == 'assist' else 'off', **options)
    return record_recognition_result(result, session.task, assets, recognition_provider, recognition_mode)


def construction_cycle(session, assets, providers, *, recognition_provider=None, recognition_mode="off",
                       run_mode="development", seconds=None, slice_seconds=30., on_progress=None,
                       _checkpoint=None, _comparisons=None, **options):
    """Advance internal slices; only online execution has a task deadline.

    At that deadline the existing batch flows through Evaluation, selection
    and Gate. Static completeness and independent CB authorization still apply.
    ``slice`` is the explicit resumable scheduler interface, not a task result.
    """
    import time
    from .construction_progress import compact_optimizer_phase, gate_outcome
    from .construction_quality import EvaluationComparisons
    from .construction_recognition import record_recognition_result, recognition_mode as check_mode
    check_mode(recognition_mode)
    if run_mode not in ('development', 'online', 'slice'):
        raise ContractError('unknown construction run mode')
    if type(slice_seconds) not in (int, float) or not math.isfinite(slice_seconds) or slice_seconds <= 0:
        raise ContractError('positive finite internal slice seconds required')
    if seconds is not None and (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0):
        raise ContractError('finite nonnegative online seconds required')
    if run_mode == 'development' and seconds is not None:
        raise ContractError('development has no task deadline; use slice_seconds for internal work')
    if on_progress is not None and not callable(on_progress):
        raise ContractError('construction progress callback must be callable')
    comparisons = _comparisons or EvaluationComparisons()
    pause_requested = options.get('pause_requested')
    started, slices = time.monotonic(), 0
    phase_history = {}
    deadline = (600. if seconds is None else seconds) if run_mode == 'online' else None
    resumable = {'time_slice_exhausted', 'iteration_slice_exhausted', 'candidate_slice_exhausted',
                 'quality_evaluation_budget', 'reference_calculation_budget', 'calculation_budget',
                 'basic_cb_requires_optimization'}
    while True:
        elapsed = time.monotonic()-started
        draining = deadline is not None and elapsed >= deadline
        work = dict(options)
        if draining:
            # Resume the generated batch, including its reference. A zero
            # candidate allowance prevents entering another S2 after S5.
            work.update(max_iterations=1, max_candidates=0, cb_authorized=False)
        duration = seconds if run_mode == 'slice' and seconds is not None else slice_seconds
        if deadline is not None and not draining:
            duration = min(duration, max(0., deadline-elapsed))
        result = _construction_cycle(session, assets, providers,
            recognition_provider=recognition_provider if recognition_mode == 'assist' else None,
            recognition_mode='assist' if recognition_mode == 'assist' else 'off', seconds=duration,
            _validate_saved=slices == 0, _comparisons=comparisons, **work)
        cb_return = result.get('basic_cb_optimization_requested', False)
        if cb_return:
            result.update(construction_passed=False, static_gate_passed=True, status='construction_suspended',
                best=None, verified_best=None)
        outcome = gate_outcome(result.get('construction_gate'))
        result['completion_status'] = ('return_to_optimizer' if cb_return else outcome)
        for phase in result.get('phases', ()):
            phase_history[phase['role'], phase.get('optimization_iteration', 0)] = compact_optimizer_phase(phase)
        result['phases'] = list(phase_history.values())
        slices += 1
        elapsed = time.monotonic() - started
        result['execution'] = dict(mode=run_mode, slices=slices, deadline_seconds=deadline,
            elapsed_seconds=elapsed, deadline_reached=deadline is not None and elapsed >= deadline)
        state = session.construction_progress or {}
        pending = bool(state.get('pending_quality') or state.get('pending_reference'))
        if pending and not cb_return:
            result['completion_status']='calculation_pending'
        paused = result['stop_reason'] == 'user_pause' or (pause_requested is not None and pause_requested())
        finished = paused or result['construction_passed'] or run_mode == 'slice'
        if not finished and draining and not pending:
            result.update(status='construction_delivered', stop_reason='online_deadline_advanced')
            result['stage_transition'] = dict(stage='S5', next_stage='S6',
                status='awaiting_static_gate_and_cb_authorization',
                reasons=(result.get('construction_gate') or {}).get('reasons', [result['stop_reason']]))
            finished = True
        if not finished and not pending and outcome in ('semantic_unimplemented', 'configuration_error'):
            # Another candidate batch cannot repair an unparsed card clause.
            # Return the precise adapter work to the development caller.
            result['stop_reason'] = ('construction_configuration_error' if outcome=='configuration_error'
                                    else 'static_coverage_unresolved')
            finished = True
        reason = result['stop_reason']
        if not pending and outcome != 'failed' and reason not in resumable:
            finished = True
        if not finished and (options.get('max_iterations') == 0 or (not pending and options.get('max_candidates') == 0)):
            result['stop_reason'] = 'internal_slice_has_no_work_allowance'
            finished = True

        def publish_progress(user_stopped):
            result['execution']['finished'] = finished or user_stopped
            if user_stopped:
                result.update(status='construction_suspended', stop_reason='user_pause', completion_status='user_stopped')
                result.pop('stage_transition', None)
            if state:
                state['stop_reason'] = result['stop_reason']
            if result.get('continuation'):
                result['continuation']['stop_reason'] = result['stop_reason']
            if _checkpoint is not None:
                _checkpoint(result)
            if on_progress is not None:
                on_progress(deepcopy(result))

        publish_progress(paused)
        if not paused and pause_requested is not None and pause_requested():
            publish_progress(True)
            finished = True
        if finished:
            break
    result = record_recognition_result(result, session.task, assets, recognition_provider, recognition_mode)
    return result if _comparisons is not None else deepcopy(result)
