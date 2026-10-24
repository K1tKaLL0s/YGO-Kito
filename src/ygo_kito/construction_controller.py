"""Concrete composition of graph selection, binding and existing coordinator."""
from .build_contracts import digest
from .construction_fill import construction_cycle
from .coord_contracts import rule_route
from .coordinator import Coordinator
from .coordinator_model import CoordinatorTrainer
from .duel_model import parameter_digest
from .validation import ContractError


class ConstructionController:
    def __init__(self, graph_adapter, binding_adapter, coordinator, *, host=None):
        if not isinstance(coordinator, CoordinatorTrainer):
            raise ContractError("existing CoordinatorTrainer required for actual learned advice")
        if host is not None and not isinstance(host, Coordinator):
            raise ContractError("existing Coordinator ledger host required")
        self.graph_adapter, self.binding_adapter = graph_adapter, binding_adapter
        self.coordinator, self.host = coordinator, host

    def bind(self, graph, task, deck):
        result=self.binding_adapter.bind(graph,task,deck,required_tags=self.graph_adapter.codec.tags)
        if result.proposal is None:
            raise ContractError("requested logic features cannot be bound: "+"; ".join(result.reasons))
        return result.proposal

    def run(self, session, *, scopes=(), base=None, verifier=None, candidate_id=None, parent_candidate_id=None):
        session.check_goal()
        if session.task.sha256 != self.graph_adapter.task.sha256:
            raise ContractError("construction controller task binding differs")
        requirements=digest(self.graph_adapter.codec.to_dict())
        previous=getattr(session,"logic_requirements_sha256",None)
        if previous is not None and previous!=requirements:
            raise ContractError("requested logic features changed; explicitly revise the user request")
        session.logic_requirements_sha256=requirements
        # A long-lived host can reuse the same model adapter across requests.
        # Only include model selections actually made in this invocation.
        self.graph_adapter.last_selection.clear()
        context={"goal_valid":False,"card_list_valid":False,"has_forecast":False,
            "warning":any(f["source"]=="duel" for f in session.feedback),"rebuild_required":False,
            "operation_error":False,"system_error":False,"remaining_tasks":2,"completed_matches":0,
            "score_mean":None,"forecast":None}
        action, reason=rule_route(context)
        advice=self.coordinator.advice(context)  # Actual existing MLP forward.
        result=construction_cycle(session,self.graph_adapter.deck_encoder.assets,self.graph_adapter.providers(),
            scopes=scopes,base=base,models=self.graph_adapter.models,encoder=self.graph_adapter.deck_encoder,
            binding_provider=self.bind,text_reviewer=self.binding_adapter.reviewer,verifier=verifier)
        result["coordinator"]={"authoritative_action":action,"reason":reason,"advice":advice,
            "mode":"existing_network_advisory_rule_authoritative"}
        result["graph_model_selections"]=dict(self.graph_adapter.last_selection)
        result["training_status"]={"classifier":session.classification.classifier_status,
            "graph_role_updates":dict(self.graph_adapter.updates),"generalization_verified":False,
            "cycle_performed_training":False}
        result["handoff"]={"status":"not_submitted"}
        if result["best"] and self.host is not None:
            if candidate_id is None:
                raise ContractError("explicit candidate ID required for coordinator ledger handoff")
            if self.host.source != "real_engine":
                raise ContractError("production controller cannot relabel a candidate as synthetic evidence")
            from .model_group import call, route_with_model
            candidate=call(self.host,"handoff.submit",{"candidate_id":candidate_id,
                "parent_candidate_id":parent_candidate_id,"task":session.task.to_dict(),"deck":result["best"]["deck"],
                "build_models":{r:parameter_digest(m) for r,m in self.graph_adapter.models.items()}})
            route, learned=route_with_model(self.host,self.coordinator,candidate["candidate_id"],None,1)
            result["handoff"]={"status":"submitted_existing_coordinator","candidate":candidate,"route":route,"advice":learned}
        session.check_goal()
        return result
