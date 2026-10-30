"""Small source/period/function-bound annotation records, not a label harvester."""

from dataclasses import dataclass

from .contracts import DEFAULT_LABEL_PROTOCOL_SHA256, ROLES, FactorContractError, RoleInput, fields, sha256_text, text, unit


@dataclass(frozen=True)
class AnnotationRecord:
    record_id: str
    example: RoleInput
    target_key: str
    role_labels: tuple[float | None, ...]
    source_refs: tuple[str, ...]
    period_ref: str | None
    annotator_ref: str
    partition: str = "development"
    definition_case: bool = True
    label_protocol_sha256: str = DEFAULT_LABEL_PROTOCOL_SHA256

    def __post_init__(self):
        for name in ("record_id", "target_key", "annotator_ref"):
            text(getattr(self, name), name)
        if not isinstance(self.example, RoleInput):
            raise FactorContractError("annotation needs exact typed context/input")
        group = next((group for group in self.example.groups if group.key == self.target_key), None)
        if group is None or group.unit is None:
            raise FactorContractError("annotation target requires its explicit function/dependency contract")
        if group.unit.period_ref != self.period_ref:
            raise FactorContractError("annotation period differs from its functional contract")
        if self.period_ref is not None:
            text(self.period_ref, "annotation period")
        if (not isinstance(self.role_labels, tuple) or len(self.role_labels) != len(ROLES)):
            raise FactorContractError("one independent role label or null per role required")
        for value in self.role_labels:
            if value is not None:
                unit(value, "annotation label")
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
        target = Targets(roles=((self.target_key, self.role_labels),))
        target.validate(self.example, source)
        return self.example, target, source

    def to_dict(self):
        return dict(schema_version="multifactor-annotation-v2", record_id=self.record_id, example=self.example.to_dict(),
                    target_key=self.target_key, role_labels=list(self.role_labels), source_refs=list(self.source_refs),
                    period_ref=self.period_ref, annotator_ref=self.annotator_ref, partition=self.partition,
                    definition_case=self.definition_case, label_protocol_sha256=self.label_protocol_sha256)

    @classmethod
    def from_dict(cls, value):
        fields(value, ("schema_version", "record_id", "example", "target_key", "role_labels", "source_refs", "period_ref",
                       "annotator_ref", "partition", "definition_case", "label_protocol_sha256"))
        if value["schema_version"] != "multifactor-annotation-v2" or not isinstance(value["role_labels"], list) or not isinstance(value["source_refs"], list):
            raise FactorContractError("versioned annotation JSON arrays required")
        return cls(**{key: (RoleInput.from_dict(item) if key == "example" else tuple(item) if key in ("role_labels", "source_refs") else item)
                      for key, item in value.items() if key != "schema_version"})
