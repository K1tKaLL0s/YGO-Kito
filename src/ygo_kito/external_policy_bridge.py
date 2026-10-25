"""Pure legal-DTO index mapping and static coverage records; no connection.

This is preparation for one pinned foreign protocol, not a WindBot executor,
provider client, native-response encoder, or historical/strength qualification.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re

from .build_contracts import digest
from .contracts import ActionSelection, DecisionRequest, validate_selection
from .validation import ContractError, array, canonical_json, fields, integer, text

UPSTREAM_PIN = "ab963c1cb9776bea4262ae1bba38f541ec70e357"
PROTOCOL = "ygoagentskill-external-policy-v1"
STATUS = "prepared_not_connected"


def _legal_request(request, observer):
    if not isinstance(request, DecisionRequest):
        raise ContractError("bridge requires the current typed player DecisionRequest")
    integer(observer, "fixed bridge observer", 0, 1)
    if request.observation.observer != observer or request.context.seed is not None:
        raise ContractError("bridge accepts only its fixed legal seat without controller RNG metadata")
    # Detach caller containers, preserving the existing hidden-information DTO
    # validation. No full deck/profile, native index/response or audit is read.
    return DecisionRequest.from_dict(json.loads(canonical_json(request.to_dict())))


def _factorized(request):
    if (request.prompt is None or request.prompt.message != 15 or request.prompt.minimum is None
            or any(a.kind not in ("select", "pass") for a in request.actions)):
        return (), {}
    refs, choices = [], {}
    for action in request.actions:
        if action.kind != "select":
            continue
        if len(set(action.card_refs)) != len(action.card_refs):
            return (), {}
        if not request.prompt.minimum <= len(action.card_refs) <= request.prompt.maximum:
            return (), {}
        key = frozenset(action.card_refs)
        if key in choices:
            return (), {}  # Same references may denote different legal operations.
        choices[key] = action.action_id
        for ref in action.card_refs:
            if ref not in refs:
                refs.append(ref)
    return tuple(refs), choices


@dataclass(frozen=True)
class PreparedIndexWindow:
    request: DecisionRequest
    state_version: str
    observer: int

    def __post_init__(self):
        text(self.state_version, "current state version")
        object.__setattr__(self, "request", _legal_request(self.request, self.observer))

    @property
    def request_sha256(self):
        return digest(self.request.to_dict())

    def packet(self):
        refs, selections = _factorized(self.request)
        return {"schema_version": 1, "status": STATUS, "upstream_pin": UPSTREAM_PIN, "protocol_candidate": PROTOCOL,
                "state_version": self.state_version, "request_sha256": self.request_sha256,
                "request": self.request.to_dict(),
                "index_space": "zero-based-order-of-this-legal-DTO-only-not-foreign-or-native-indices",
                "factorizedSelection": bool(selections),
                "selectionCandidates": [{"index": index, "ref": ref} for index, ref in enumerate(refs)],
                "provider_connected": False, "native_response_generated": False}

    def translate(self, reply, *, current_request, current_state_version):
        current = _legal_request(current_request, self.observer)
        d = fields(reply, {"state_version", "request_sha256"}, {"actionIndex", "index", "selectionIndexes"})
        if (current_state_version != self.state_version or d["state_version"] != self.state_version
                or digest(current.to_dict()) != self.request_sha256 or d["request_sha256"] != self.request_sha256):
            raise ContractError("stale or mismatched prepared legal window")
        selectors = set(d) & {"actionIndex", "index", "selectionIndexes"}
        if len(selectors) != 1:
            raise ContractError("choose exactly one index selector; mixed/empty responses are rejected")
        mode = next(iter(selectors))
        if mode == "selectionIndexes":
            refs, choices = _factorized(current)
            if not choices:
                raise ContractError("factorized selection is unsupported or ambiguous for this legal window")
            indexes = array(d[mode], "selection indexes")
            for index in indexes:
                integer(index, "selection index", 0, len(refs) - 1)
            if len(set(indexes)) != len(indexes):
                raise ContractError("selection indexes must be unique")
            if not current.prompt.minimum <= len(indexes) <= current.prompt.maximum:
                raise ContractError("selection count outside the current offered bounds")
            action_id = choices.get(frozenset(refs[index] for index in indexes))
            if action_id is None:
                raise ContractError("selected combination is not an existing legal action")
        else:
            integer(d[mode], "action index", 0, len(current.actions) - 1)
            action_id = current.actions[d[mode]].action_id
        selection = ActionSelection(current.context.run_id, current.duel_id, current.decision_id, action_id)
        validate_selection(current, selection)
        return {"status": STATUS, "method": "duel.submit_action",
                "params": {"state_version": current_state_version, "action_id": action_id},
                "provider_connected": False, "action_submitted": False, "native_response_generated": False}


def _sha(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ContractError(label + " must be a lowercase SHA256")


def _source_path(value):
    text(value, "pinned source path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ContractError("source path must be a repository-relative metadata path")


def coverage_matrix(period_ids, samples, drivers, *, listing_checks=()):
    """Complete Cartesian inventory; static listing checks never grant runtime.

    Callers provide the statically audited source IDs, never guessed themes.
    Matrix records do not execute a driver or authenticate supplied evidence.
    """
    periods = list(period_ids)
    for period in periods:
        text(period, "period ID")
    if not periods or len(set(periods)) != len(periods):
        raise ContractError("unique explicit period IDs required")
    sample_rows, driver_rows = {}, {}
    for sample in samples:
        d = fields(sample, {"sample_id", "deck_sha256", "artifact_sha256", "source_pin", "source_path"})
        text(d["sample_id"], "sample ID")
        if d["sample_id"] in sample_rows or d["source_pin"] != UPSTREAM_PIN:
            raise ContractError("sample identity repeats or is outside the statically reviewed pin")
        _sha(d["deck_sha256"], "deck content"); _sha(d["artifact_sha256"], "source artifact")
        _source_path(d["source_path"])
        sample_rows[d["sample_id"]] = deepcopy(d)
    for driver in drivers:
        d = fields(driver, {"driver_id", "source_pin", "source_path", "mode"})
        text(d["driver_id"], "driver ID")
        if (d["driver_id"] in driver_rows or d["source_pin"] != UPSTREAM_PIN
                or d["mode"] not in ("deck_executor", "external_policy_only")):
            raise ContractError("driver identity/pin/mode differs from static inventory")
        _source_path(d["source_path"])
        driver_rows[d["driver_id"]] = deepcopy(d)
    if not sample_rows or not driver_rows:
        raise ContractError("nonempty sample and driver inventories required")
    checks = {}
    for supplied in listing_checks:
        d = fields(supplied, {"period_id", "sample_id", "deck_sha256", "status", "evidence_sha256"}, {"source_status"})
        key = (d["period_id"], d["sample_id"])
        if key in checks or d["period_id"] not in periods or d["sample_id"] not in sample_rows:
            raise ContractError("listing record is duplicate or outside the explicit matrix")
        if d["status"] not in ("unverified", "blocked", "rejected", "checked_under_supplied_evidence"):
            raise ContractError("listing status cannot claim rule or strength qualification")
        if d["deck_sha256"] != sample_rows[d["sample_id"]]["deck_sha256"]:
            raise ContractError("listing evidence names a different sample deck")
        _sha(d["evidence_sha256"], "static listing evidence")
        checks[key] = deepcopy(d)
    rows = []
    for period in periods:
        for sample_id, sample in sample_rows.items():
            for driver_id, driver in driver_rows.items():
                identity = {"period_id": period, "sample_id": sample_id, "driver_id": driver_id,
                            "deck_sha256": sample["deck_sha256"], "source_pin": UPSTREAM_PIN}
                rows.append(dict(identity, row_id=digest(identity),
                    listing=deepcopy(checks.get((period, sample_id), {"status": "unverified", "evidence_sha256": None})),
                    deck_driver_match="not_checked", driver_execution="not_run",
                    index_adapter=STATUS if driver["mode"] == "external_policy_only" else "not_assessed",
                    normal_operational=False, native_rules_verified=False, historical_rules_verified=False,
                    operation_qualified=False, strength_qualified=False))
    result = {"schema_version": 1, "kind": "static-period-sample-driver-coverage", "source_pin": UPSTREAM_PIN,
              "period_ids": periods, "samples": list(sample_rows.values()), "drivers": list(driver_rows.values()),
              "rows": rows, "native_executed": False, "provider_connected": False,
              "formal_training_ready": False, "qualification_inferred_from_listing": False}
    result["matrix_sha256"] = digest(result)
    return result


def coverage_from_listing_audit(audit, drivers):
    """Project the existing source audit's pinned third-party samples only.

    Engineering profiles and any user-deck entries are not relabelled WindBot
    samples. Full static-check content is bound by digest, never upgraded to a
    runtime or qualified-driver claim.
    """
    if (not isinstance(audit, dict) or type(audit.get("schema_version")) is not int
            or audit["schema_version"] != 1 or not isinstance(audit.get("periods"), dict)):
        raise ContractError("source audit schema/explicit periods required")
    samples, checks = [], []
    statuses = {name: name for name in ("unverified", "blocked", "rejected", "checked_under_supplied_evidence")}
    statuses["blocked_cutoff_unspecified"] = "blocked"
    statuses["blocked_future_cutoff_staging_only"] = "blocked"
    for sample in array(audit.get("samples"), "source-audited samples"):
        if sample.get("dataset_kind") != "third_party_sample_not_user_deck":
            continue
        if sample.get("user_deck") is not False:
            raise ContractError("a user deck cannot be relabelled a static third-party sample")
        source = sample["source"]
        samples.append({"sample_id": sample["sample_id"], "deck_sha256": sample["deck_sha256"],
            "artifact_sha256": source["artifact_sha256"], "source_pin": source["source_pin"], "source_path": source["source_path"]})
        for check in array(sample["checks"], "per-period source checks"):
            status = check["historical_listing_status"]
            if status not in statuses:
                raise ContractError("source listing status cannot claim runtime qualification")
            checks.append({"period_id": check["period_id"], "sample_id": sample["sample_id"],
                "deck_sha256": sample["deck_sha256"], "status": statuses[status],
                "source_status": status, "evidence_sha256": digest(check)})
    result = coverage_matrix(list(audit["periods"]), samples, drivers, listing_checks=checks)
    result.pop("matrix_sha256")
    result["listing_audit_sha256"] = digest(audit)
    result["matrix_sha256"] = digest(result)
    return result


def coverage_from_source_inventory(inventory, audit):
    if (inventory.get("schema_version") != 1 or inventory.get("commit") != UPSTREAM_PIN
            or not isinstance(inventory.get("drivers"), list)):
        raise ContractError("fixed source inventory and actual driver metadata required")
    drivers = [{"driver_id": driver["driver_id"], "source_path": driver["source_path"],
                "source_pin": inventory["commit"], "mode": driver["mode"]} for driver in inventory["drivers"]]
    result = coverage_from_listing_audit(audit, drivers)
    result.pop("matrix_sha256")
    result["driver_inventory_sha256"] = digest(inventory)
    result["local_operational_references"] = []
    result["matrix_sha256"] = digest(result)
    return result


def attach_local_snapshot_proof(matrix, proof, *, expected_scope):
    """Bind a trusted host's real sampling summary, never a policy reply.

    This performs metadata/hash checks only. The actual sampling/replay remains
    the trusted producer's responsibility and is not executed by this layer.
    Local Python snapshot evidence never qualifies a foreign WindBot row.
    """
    result = deepcopy(matrix)
    claimed = result.pop("matrix_sha256", None)
    if (claimed != digest(result) or result.get("kind") != "static-period-sample-driver-coverage"
            or result.get("source_pin") != UPSTREAM_PIN):
        raise ContractError("coverage matrix changed before evidence attachment")
    d = fields(proof, {"schema_version", "kind", "scope", "source_component", "passed", "training_updates_this_check",
                       "historical_training_verified", "historical_rules_verified", "strength_qualified",
                       "applies_to_matrix_rows", "summary_sha256"},
               {"source_group_boundary", "native_executed", "fault_injection_performed"})
    original = deepcopy(d); original.pop("summary_sha256")
    if (type(d["schema_version"]) is not int or d["schema_version"] != 1
            or d["kind"] != "actual-period-local-snapshot-engineering" or digest(original) != d["summary_sha256"]):
        raise ContractError("actual local snapshot proof identity/checksum differs")
    scope_keys = {"period_id", "period_context", "versions", "resources", "profile_sha256", "own_deck_sha256",
                  "opponent_deck_sha256", "model_sha256", "driver_version", "driver_implementation_sha256", "controller"}
    scope = fields(d["scope"], scope_keys)
    fields(expected_scope, scope_keys)
    if (scope != expected_scope or scope["period_id"] not in result["period_ids"]
            or scope["controller"] != "local_snapshot" or scope["period_context"].get("period_id") != scope["period_id"]):
        raise ContractError("local operational proof differs from the exact expected scope")
    for name in ("profile_sha256", "own_deck_sha256", "opponent_deck_sha256", "model_sha256", "driver_implementation_sha256"):
        _sha(scope[name], name)
    from .contracts import Versions
    Versions.from_dict(scope["versions"])
    text(scope["driver_version"], "local snapshot driver version")
    if not isinstance(scope["resources"], dict) or not scope["resources"]:
        raise ContractError("actual resource hash receipt required")
    for checksum in scope["resources"].values():
        _sha(checksum, "runtime resource")
    passed = fields(d["passed"], {"normal_sampling", "natural_terminal", "private_replay", "source_checkpoint_restore",
                                  "host_reload_binding", "actor_rebind", "weights_frozen"})
    if (not all(value is True for value in passed.values()) or d["applies_to_matrix_rows"] != []
            or type(d["training_updates_this_check"]) is not int or d["training_updates_this_check"] != 0
            or any(d[key] is not False for key in ("historical_training_verified", "historical_rules_verified", "strength_qualified"))
            or d.get("fault_injection_performed", False) is not False or d.get("native_executed", True) is not True):
        raise ContractError("local proof lacks successful normal checks or overclaims qualification")
    component = fields(d["source_component"], {"name", "group_checkpoint_sha256", "model_sha256", "completed_boundary",
                                              "updated_base_component", "lora_snapshot", "extracted_artifact_sha256"},
                       {"source_group_boundary", "completed_updates"})
    if (component["name"] != "components.duel" or component["model_sha256"] != scope["model_sha256"]
            or component["completed_boundary"] != "complete-episode" or component["updated_base_component"] is not True
            or component["lora_snapshot"] is not False):
        raise ContractError("local evidence must name its actual updated frozen base component")
    for boundary in (d.get("source_group_boundary"), component.get("source_group_boundary")):
        if boundary is not None and boundary != "complete-workflow-stage":
            raise ContractError("source group checkpoint boundary differs")
    if "completed_updates" in component:
        integer(component["completed_updates"], "completed source base updates", 1)
    _sha(component["group_checkpoint_sha256"], "source group artifact")
    _sha(component["extracted_artifact_sha256"], "explicit frozen inference artifact")
    references = result.setdefault("local_operational_references", [])
    identity = digest(scope)
    existing = next((row for row in references if row["scope_sha256"] == identity), None)
    if existing is not None and existing["proof_sha256"] != d["summary_sha256"]:
        raise ContractError("different local evidence already occupies this exact operational scope")
    if existing is None:
        references.append({"scope": deepcopy(scope), "scope_sha256": identity, "proof_sha256": d["summary_sha256"],
            "source_component": deepcopy(component), "normal_operational": True, "model_role": "opponent",
            "historical_training_verified": False, "historical_rules_verified": False, "strength_qualified": False,
            "training_checkpoint_recovery_verified": False, "applies_to_matrix_rows": [],
            "validation_scope": "trusted-summary-hash-and-exact-scope-only-not-replayed-by-this-module"})
    result["matrix_sha256"] = digest(result)
    return result
