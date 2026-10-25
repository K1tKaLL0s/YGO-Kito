"""Indexed, host-labelled course feedback on the existing LoRA sessions.

No duel result is converted to a quality or win-rate label here. The caller
supplies an explicit training artifact/label; held-out artifacts fail before a
loss or update. The containing course transaction owns model/index checkpoints.
"""
from copy import deepcopy

from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, digest
from .build_training import BuildTrainer, validate_supervision
from .coordinator_model import CoordinatorTrainer, supervision_rows
from .data_isolation import DataIndex, ConstructionAdmission
from .duel_model import parameter_digest
from .lora import AdapterSession
from .lora_group import construction_loss, coordinator_loss as actual_coordinator_loss
from .semantic_training import SOURCE
from .validation import ContractError

FEATURE_VERSION="indexed-explicit-course-feedback-v1"
BUILD_ROLES=("build_goal","build_optimizer")


class CourseFeedbackUpdater:
    def __init__(self, models, data_index, experiment_id):
        identifier(experiment_id)
        if (not isinstance(data_index,DataIndex) or not isinstance(models.builder,BuildTrainer) or
                not isinstance(models.coordinator,CoordinatorTrainer)):
            raise ContractError("existing course models and typed data index required")
        sessions=models.sessions
        actual=dict(models.builder.models,coordinator=models.coordinator.model)
        if any(not isinstance(sessions.get(r),AdapterSession) or sessions[r].model is not actual[r]
               or sessions[r].config.role!=r for r in (*BUILD_ROLES,"coordinator")):
            raise ContractError("actual independent existing role LoRA sessions required")
        self.models,self.index,self.experiment_id=models,data_index,experiment_id
        self._sessions={r:sessions[r] for r in (*BUILD_ROLES,"coordinator")}
        self._models_binding=deepcopy(getattr(models,"binding",{}))
        self.binding={"feature_version":FEATURE_VERSION,"experiment_id":experiment_id,
            "models_binding":self._models_binding,"vocabulary_sha256":models.builder.encoder.vocabulary_sha256}
        self.binding_sha256=digest(self.binding)
        self.consumed=[]
        self.pending=None

    def _check(self):
        if (getattr(self.models,"binding",{})!=self._models_binding or
                digest(self.binding)!=self.binding_sha256 or
                self.models.builder.encoder.vocabulary_sha256!=self.binding["vocabulary_sha256"] or
                any(self.models.sessions.get(r) is not s for r,s in self._sessions.items())):
            raise ContractError("course feedback models/session/vocabulary binding changed")
        actual=dict(self.models.builder.models,coordinator=self.models.coordinator.model)
        for role,session in self._sessions.items():
            if session.model is not actual[role]:raise ContractError("feedback role model was replaced")
            session.verify_base()

    def _artifact(self,artifact_id,*,task=None):
        self._check()
        artifact=self.index.artifact(artifact_id,for_training=True)
        dataset=self.index.dataset(artifact["dataset_id"])
        if dataset["experiment_id"]!=self.experiment_id:
            raise ContractError("feedback artifact belongs to a different experiment")
        if dataset["versions"]!=self.models.builder.task.environment["versions"]:
            raise ContractError("feedback artifact environment differs from the actual course")
        admission=None
        if task is not None:
            if not isinstance(task,BuildTask) or artifact["family"]!="construction":
                raise ContractError("indexed construction artifact and typed task required")
            admission=self.index.admit_construction(artifact_id,task,artifact["payload"])
            if not isinstance(admission,ConstructionAdmission) or admission.index is not self.index:
                raise ContractError("actual construction admission required")
            if artifact["payload"].get("source")!=SOURCE:
                raise ContractError("course construction feedback requires explicit indexed semantic data")
            validate_supervision(task,self.models.builder.encoder.assets,artifact["payload"])
            self.models.builder.encoder.encode(task,DeckParts(()))
        return artifact,dataset,admission

    def _prepare(self,feedback_id,artifact,request,roles):
        identifier(feedback_id)
        if self.pending is not None:
            raise ContractError("an interrupted feedback update requires course transaction inspection/restore")
        request_sha=digest(request)
        content_keys={r:digest({"role":r,"artifact_payload_sha256":artifact["payload_sha256"],"request":request}) for r in roles}
        if (any(r["feedback_id"]==feedback_id or r["content_key"] in content_keys.values() for r in self.consumed)):
            raise ContractError("feedback id or the same indexed feedback content was already consumed")
        for role in roles:
            session=self._sessions[role]
            if session.detached or not session.enabled or session.updates>=session.config.max_updates:
                raise ContractError("feedback role adapter is inactive or its explicit update limit is exhausted")
        return request_sha,content_keys

    def _step(self,feedback_id,artifact,request_sha,content_key,role,loss_factory,*,label_source):
        session=self._sessions[role]
        before=parameter_digest(session.model)
        # Validation/loss construction does not consume an update. Only the
        # optimizer boundary can leave an uncertain partially applied step.
        loss=loss_factory()
        self.pending={"feedback_id":feedback_id,"artifact_id":artifact["artifact_id"],"role":role,
            "before_sha256":before,"adapter_updates_before":session.updates,"outcome":"started"}
        try:
            update=session.step(loss)
            after=parameter_digest(session.model)
            if before==after:raise ContractError("actual feedback session did not change role parameters")
            if role in BUILD_ROLES and getattr(self.models,"kernel",None) is not None:
                self.models.kernel.record_update(role,before_sha256=before,after_sha256=after)
            result={"feedback_id":feedback_id,"artifact_id":artifact["artifact_id"],"role":role,
                "artifact_payload_sha256":artifact["payload_sha256"],"request_sha256":request_sha,
                "content_key":content_key,"before_sha256":before,"after_sha256":after,
                "label_source":label_source,"indexed_purpose":"train","update":update,
                "ability_verified":False,"quality_inferred_from_single_duel":False}
            self.consumed.append(result)
            self.pending=None
            return deepcopy(result)
        except Exception:
            self.pending["outcome"]="failed_or_uncertain_do_not_replay"
            self.pending["after_sha256"]=parameter_digest(session.model)
            self.pending["adapter_updates_after"]=session.updates
            raise

    def apply_construction(self,feedback_id,artifact_id,task,*,roles=BUILD_ROLES):
        if not isinstance(roles,(list,tuple)) or not roles or len(set(roles))!=len(roles) or any(r not in BUILD_ROLES for r in roles):
            raise ContractError("explicit distinct construction roles required")
        artifact,_,admission=self._artifact(artifact_id,task=task)
        request={"kind":"indexed_semantic_construction","task_sha256":task.sha256}
        request_sha,keys=self._prepare(feedback_id,artifact,request,roles)
        return [self._step(feedback_id,artifact,request_sha,keys[role],role,
            lambda role=role:construction_loss(role,self._sessions[role],self.models.builder,task,artifact["payload"],data_admission=admission),
            label_source="explicit_catalog_constraints_and_user_preferences_not_strength") for role in roles]

    def apply_coordinator(self,feedback_id,artifact_id,examples):
        artifact,dataset,_=self._artifact(artifact_id)
        rows,synthetic=supervision_rows(examples)
        if synthetic or examples["source"]!="host_logged_supervision_v1":
            raise ContractError("explicit host logged coordinator feedback required; no synthetic probability default")
        for row in rows:
            provenance=row["provenance"]
            if (provenance["dataset_id"]!=dataset["dataset_id"] or provenance["record_id"]!=artifact_id or
                    provenance["evidence_sha256"]!=artifact["payload_sha256"]):
                raise ContractError("coordinator label must reference the exact indexed training record")
        request={"kind":"explicit_host_coordinator_labels","examples_sha256":digest(examples)}
        request_sha,keys=self._prepare(feedback_id,artifact,request,("coordinator",))
        return self._step(feedback_id,artifact,request_sha,keys["coordinator"],"coordinator",
            lambda:actual_coordinator_loss(self._sessions["coordinator"],examples),label_source="explicit_host_logged_not_calibrated_win_rate")

    def apply_task_preference(self,feedback_id,artifact_id,proposals,preferred_id,*,source="human_preference"):
        kernel=getattr(self.models,"kernel",None)
        if kernel is None:raise ContractError("actual autonomous construction kernel required")
        candidate=next((c for c in proposals.get("candidates",[]) if c["candidate_id"]==preferred_id),None)
        if candidate is None:raise ContractError("explicit preferred task is absent")
        task=BuildTask.from_dict(candidate["task"])
        artifact,_,_=self._artifact(artifact_id,task=task)
        request={"kind":"explicit_task_preference","proposal_sha256":proposals.get("proposal_sha256"),
            "preferred_id":preferred_id,"source":source}
        request_sha,keys=self._prepare(feedback_id,artifact,request,("build_goal",))
        return self._step(feedback_id,artifact,request_sha,keys["build_goal"],"build_goal",
            lambda:kernel.preference_loss(proposals,preferred_id,source=source,purpose="train")["loss"],
            label_source="explicit_admitted_host_preference_not_automatic_strength")

    def apply_graph_preference(self,feedback_id,artifact_id,selection,preferred_index,*,role="build_optimizer",source="human_preference"):
        kernel=getattr(self.models,"kernel",None)
        if kernel is None or role not in BUILD_ROLES:raise ContractError("actual construction kernel/role required")
        task=kernel._selection(selection)
        artifact,_,_=self._artifact(artifact_id,task=task)
        session,_=kernel._session(selection)
        request={"kind":"explicit_graph_preference","task_sha256":task.sha256,"logic_sha256":session.logic.sha256 if session.logic else None,
            "feedback_sha256":digest(session.feedback),"preferred_index":preferred_index,"source":source}
        request_sha,keys=self._prepare(feedback_id,artifact,request,(role,))
        return self._step(feedback_id,artifact,request_sha,keys[role],role,
            lambda:kernel.graph_preference_loss(selection,preferred_index,role=role,source=source,purpose="train")["loss"],
            label_source="explicit_admitted_host_graph_preference_not_automatic_strength")

    def state_dict(self):
        self._check()
        state={"schema_version":1,"feature_version":FEATURE_VERSION,"binding_sha256":self.binding_sha256,
            "model_hashes":{r:parameter_digest(s.model) for r,s in self._sessions.items()},
            "consumed":deepcopy(self.consumed),"pending":deepcopy(self.pending),"weights_owned_by_course_checkpoint":True}
        state["metadata_sha256"]=digest(state)
        return state

    def load_state_dict(self,state):
        self._check()
        if (not isinstance(state,dict) or state.get("schema_version")!=1 or state.get("feature_version")!=FEATURE_VERSION or
                state.get("binding_sha256")!=self.binding_sha256 or
                state.get("model_hashes")!={r:parameter_digest(s.model) for r,s in self._sessions.items()} or
                state.get("metadata_sha256")!=digest({k:v for k,v in state.items() if k!="metadata_sha256"})):
            raise ContractError("feedback restore requires exact model/index/course metadata")
        rows=deepcopy(state["consumed"])
        if not isinstance(rows,list) or len({r["content_key"] for r in rows})!=len(rows):
            raise ContractError("duplicate/malformed consumed feedback records")
        for row in rows:
            artifact,_,_=self._artifact(row["artifact_id"])
            if artifact["payload_sha256"]!=row["artifact_payload_sha256"] or row["role"] not in self._sessions:
                raise ContractError("consumed feedback no longer has its exact indexed training record")
        self.consumed=rows
        self.pending=deepcopy(state["pending"])
