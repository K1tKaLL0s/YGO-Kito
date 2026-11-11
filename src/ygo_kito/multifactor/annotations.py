"""Small source/period/function-bound annotation records, not a label harvester."""

from dataclasses import dataclass

from .contracts import DEFAULT_LABEL_PROTOCOL_SHA256, ROLES, FactorContractError, LabelCell, LabelSet, RoleInput, fields, sha256_text, text


@dataclass(frozen=True)
class AnnotationRecord:
    record_id: str
    example: RoleInput
    target_key: str
    role_labels: tuple[LabelCell, ...]
    source_refs: tuple[str, ...]
    period_ref: str | None
    annotator_ref: str
    partition: str = "development"
    definition_case: bool = True
    label_protocol_sha256: str = DEFAULT_LABEL_PROTOCOL_SHA256
    task_labels: tuple[LabelSet, ...] = ()

    def __post_init__(self):
        for name in ("record_id", "target_key", "annotator_ref"):
            text(getattr(self, name), name)
        if not isinstance(self.example, RoleInput):
            raise FactorContractError("annotation needs exact typed context/input")
        group = next((group for group in self.example.groups if group.key == self.target_key), None)
        if group is None or group.unit is None and self.example.unit_definition is None:
            raise FactorContractError("annotation target requires its explicit function/dependency contract")
        if group.unit is not None and group.unit.period_ref != self.period_ref:
            raise FactorContractError("annotation period differs from its functional contract")
        if self.example.analysis_context is not None and self.example.analysis_context.period not in ("unknown", self.period_ref):
            raise FactorContractError("annotation period differs from analysis context")
        if self.period_ref is not None:
            text(self.period_ref, "annotation period")
        if (not isinstance(self.role_labels, tuple) or len(self.role_labels) != len(ROLES)):
            raise FactorContractError("one independent role label or null per role required")
        object.__setattr__(self, "role_labels", tuple(LabelCell.from_legacy(v).validate_domain() for v in self.role_labels))
        if not isinstance(self.task_labels, tuple) or any(not isinstance(v, LabelSet) for v in self.task_labels):
            raise FactorContractError("typed task label sets required")
        if (not isinstance(self.source_refs, tuple) or not 1 <= len(self.source_refs) <= 16):
            raise FactorContractError("annotation source references required")
        for source in self.source_refs:
            text(source, "annotation source")
        if self.partition not in ("development", "train", "validation", "final_eval") or type(self.definition_case) is not bool:
            raise FactorContractError("explicit annotation purpose required")
        if self.definition_case and self.partition != "development":
            raise FactorContractError("definition/development examples cannot be relabeled as independent evaluation or real training")
        sha256_text(self.label_protocol_sha256, "annotation label protocol")

    def training_view(self):
        from .training import Supervision, Targets
        if self.partition in ("validation", "final_eval"):
            raise FactorContractError("held-out annotations are not training inputs")
        source = Supervision("definition_development" if self.partition == "development" else "human_feedback",
                             " | ".join(self.source_refs), label_protocol_sha256=self.label_protocol_sha256)
        target = Targets(roles=((self.target_key, self.role_labels),), task_labels=self.task_labels)
        target.validate(self.example, source)
        return self.example, target, source

    def to_dict(self):
        return dict(schema_version="multifactor-annotation-v3", record_id=self.record_id, example=self.example.to_dict(),
                    target_key=self.target_key, role_labels=[v.to_dict() for v in self.role_labels], source_refs=list(self.source_refs),
                    period_ref=self.period_ref, annotator_ref=self.annotator_ref, partition=self.partition,
                    definition_case=self.definition_case, label_protocol_sha256=self.label_protocol_sha256,
                    task_labels=[v.to_dict() for v in self.task_labels])

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise FactorContractError("annotation object required")
        if value.get("schema_version") == "multifactor-annotation-v3":
            fields(value, ("schema_version", "record_id", "example", "target_key", "role_labels", "source_refs", "period_ref",
                           "annotator_ref", "partition", "definition_case", "label_protocol_sha256", "task_labels"))
            if any(not isinstance(value[k], list) for k in ("role_labels", "source_refs", "task_labels")):
                raise FactorContractError("annotation arrays required")
            return cls(value["record_id"], RoleInput.from_dict(value["example"]), value["target_key"],
                       tuple(LabelCell.from_dict(v) for v in value["role_labels"]), tuple(value["source_refs"]),
                       value["period_ref"], value["annotator_ref"], value["partition"], value["definition_case"],
                       value["label_protocol_sha256"], tuple(LabelSet.from_dict(v) for v in value["task_labels"]))
        fields(value, ("schema_version", "record_id", "example", "target_key", "role_labels", "source_refs", "period_ref",
                       "annotator_ref", "partition", "definition_case", "label_protocol_sha256"))
        if value["schema_version"] != "multifactor-annotation-v2" or not isinstance(value["role_labels"], list) or not isinstance(value["source_refs"], list):
            raise FactorContractError("versioned annotation JSON arrays required")
        return cls(**{key: (RoleInput.from_dict(item) if key == "example" else tuple(item) if key in ("role_labels", "source_refs") else item)
                      for key, item in value.items() if key != "schema_version"})
