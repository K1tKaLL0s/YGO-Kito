"""Stage 3 adapters to existing fill/rank/list/goal interfaces.

Text reviews are explicit, source-bound assessments, not a new effect parser.
The existing goal verifier cannot certify an arbitrary lightweight graph as a CB.
"""

from dataclasses import asdict, dataclass
from copy import deepcopy
import math

from .build_contracts import DeckParts, digest
from .construction_logic import LogicTag, reachable, select_main_axes, short
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


def evaluate_fill(session, assets, proposal, *, scopes=(), text_reviewer=None, verifier=existing_goal_verifier):
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
            output["fallback"] = deepcopy(prior)
        session.record_feedback("fill", message)
        return output

    axes = select_main_axes(task, assets, session.classification, scopes)
    output["stage_2"] = axes
    output["scope_sha256"] = digest({"intent": session.classification.to_dict(), "selection": axes})
    if axes["status"] not in ("selected", "skipped_broad"):
        return reject(axes["status"], "entry intent or requested theme facts must be resolved before filling")
    nodes = _check_bindings(graph, proposal)
    try:
        assets.validate(task, proposal.deck)
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
    output["engine_validation"] = proof
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


def fill_with_existing(session, assets, *, role="build_goal", base=None, models=None, encoder=None,
                       binding_provider=None, text_reviewer=None, scopes=(), verifier=existing_goal_verifier):
    """Reuse existing fill/quantity generation and independent model ranking.

    A binding provider adapts actual fill candidates to the abstract graph. This
    change supplies no graph-generation/binding weights and does not train them.
    """
    from .build_pipeline import edit_candidates, goal_candidates
    member(role, "fill role", ("build_goal", "build_optimizer"))
    session.check_goal()
    if session.logic is None:
        raise ContractError("stage 1 construction logic is required")
    if binding_provider is None:
        return {"status": "binding_provider_unavailable", "training_status": "engineering_untrained", "best_deck": None}
    task = session.task
    axes = select_main_axes(task, assets, session.classification, scopes)
    if axes["status"] not in ("selected", "skipped_broad"):
        return {"status": axes["status"], "stage_2": axes, "best_deck": None}
    if role == "build_optimizer" and base is None:
        raise ContractError("optimizer filling requires an existing concrete deck")
    candidates = (goal_candidates(task, assets, base) if role == "build_goal"
                  else edit_candidates(task, assets, base, require_edit=True))
    scores, ranking = [0.] * len(candidates), "engineering_order_untrained"
    if models is not None:
        if encoder is None or role not in models:
            raise ContractError("existing role model and bound encoder required together")
        if candidates:
            import torch
            models[role].eval()
            with torch.no_grad():
                scores = models[role](encoder.batch(task, candidates)).tolist()
            if len(scores) != len(candidates) or any(not math.isfinite(s) for s in scores):
                raise ContractError("invalid existing model candidate scores")
        ranking = "existing_role_model_uncalibrated"
    results = []
    for index in sorted(range(len(candidates)), key=lambda i: -scores[i]):
        proposal = binding_provider(session.logic, task, candidates[index])
        if not isinstance(proposal, FillProposal) or proposal.deck != candidates[index]:
            raise ContractError("binding provider must preserve the generated candidate and quantities")
        result = evaluate_fill(session, assets, proposal, scopes=scopes, text_reviewer=text_reviewer, verifier=verifier)
        result.update(role=role, ranking=ranking, model_score_uncalibrated=scores[index])
        results.append(result)
        if result["status"] in ("task_goal_verified_logic_unproven", "list_constraints_verified_logic_unproven"):
            return {"status": result["status"], "best_deck": result["best_deck"], "attempts": results,
                    "ranking": ranking, "graph_execution_verified": False}
    return {"status": "no_verified_fill_within_candidates", "best_deck": results[-1]["best_deck"] if results else None,
            "attempts": results, "ranking": ranking, "graph_execution_verified": False}


def construction_cycle(session, assets, providers, *, scopes=(), base=None, models=None, encoder=None,
                       binding_provider=None, text_reviewer=None, verifier=existing_goal_verifier):
    """Coordinator: target stages 1/2/3 → optimizer stages 1/2/3.

    Fill/duel/user feedback remains available to later cycles. A failed new
    revision can return an earlier task-verified candidate only WITH its original
    graph and proof; it never promotes it as evidence for the latest revision.
    """
    phases, best, current = [], None, base
    for role in ("build_goal", "build_optimizer"):
        revision = session.propose_logic(role, providers.get(role))
        phase = {"role": role, "stage_1": revision}
        phases.append(phase)
        if revision["status"] != "logic_revised":
            break
        graph = session.logic
        phase["stage_2"] = select_main_axes(session.task, assets, session.classification, scopes)
        session.history.append({"stage": 2, "role": role, "logic_sha256": graph.sha256,
                                "goal_sha256": session.goal_sha256, "result": deepcopy(phase["stage_2"])})
        if phase["stage_2"]["status"] not in ("selected", "skipped_broad"):
            session.record_feedback("fill", "theme-axis phase unresolved: " + phase["stage_2"]["status"])
            break
        # If a target fill fails, ask the target again after feedback rather than
        # manufacture an optimizer base or silently relax the goal.
        result = fill_with_existing(session, assets, role=role, base=current, models=models, encoder=encoder,
            binding_provider=binding_provider, text_reviewer=text_reviewer, scopes=scopes, verifier=verifier)
        phase["stage_3"] = result
        session.history.append({"stage": 3, "role": role, "logic_sha256": graph.sha256,
                                "goal_sha256": session.goal_sha256, "result": deepcopy(result)})
        if result["status"] not in ("task_goal_verified_logic_unproven", "list_constraints_verified_logic_unproven"):
            session.record_feedback(role, "fill phase unresolved: " + result["status"])
            break
        current = DeckParts.from_dict(result["best_deck"])
        best = {"deck": result["best_deck"], "logic": graph.to_dict(), "logic_sha256": graph.sha256,
                "validation": result, "goal_sha256": session.goal_sha256}
        session.record_feedback(role, "concrete task goal checked; lightweight graph execution remains unverified")
    return {"status": "task_checked_candidate" if best else "construction_unresolved", "phases": phases,
            "best": best, "latest_logic_sha256": session.logic.sha256 if session.logic else None,
            "goal_sha256": session.goal_sha256, "graph_execution_verified": False,
            "training_status": "engineering_integration_no_graph_training"}
