"""Actual CPU supervised updates for independent goal/optimizer rankers.

Goal supervision uses real conditional routes or explicit hard-constraint failure.
Optimization supervision is an openly marked engineering proxy, never strength.
"""

from dataclasses import asdict, dataclass, field
import hashlib
import math
import os
from pathlib import Path
import platform
import random

import torch
from torch.nn import functional as F

from .agent_monitor import RunMonitor, RunReporter
from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, digest
from .build_model import BuildEncoder, BuildModelConfig, BuildRanker, FEATURE_VERSION
from .build_pipeline import BuildAssets, alternate_build, edit_candidates, engineering_proxy, goal_candidates, verify_goal
from .cpu_training import cpu_name
from .duel_model import parameter_digest
from .device import (resolve_device, execution_metadata, checkpoint_device, optimizer_to,
                     capture_device_rng, restore_device_rng, checkpoint_execution)
from .validation import ContractError, array, canonical_json, fields, integer

ROLES = ("build_goal", "build_optimizer")


@dataclass(frozen=True)
class BuildTrainingConfig:
    model: BuildModelConfig = field(default_factory=BuildModelConfig)
    learning_rate: float = .001
    model_seeds: tuple = (321, 654)
    batch_seed: int = 987
    batches: int = 2

    def __post_init__(self):
        if not isinstance(self.model, BuildModelConfig):
            raise ContractError("typed build model configuration required")
        if type(self.learning_rate) not in (int, float) or not math.isfinite(self.learning_rate) or not 0 < self.learning_rate <= .01:
            raise ContractError("CPU building learning rate outside proof range")
        if not isinstance(self.model_seeds, tuple) or len(self.model_seeds) != 2:
            raise ContractError("two independent model seeds required")
        for seed in (*self.model_seeds, self.batch_seed):
            integer(seed, "building RNG seed", 0, 2**32 - 8)
        integer(self.batches, "building batches", 1, 100000)


def config_from_dict(value):
    d = dict(fields(value, set(), set(BuildTrainingConfig.__dataclass_fields__) | {"schema_version"}))
    integer(d.pop("schema_version", 1), "build training config schema", 1, 1)
    d["model"] = BuildModelConfig(**fields(d.get("model", {}), set(), set(BuildModelConfig.__dataclass_fields__)))
    if "model_seeds" in d:
        if not isinstance(d["model_seeds"], (list, tuple)):
            raise ContractError("model seeds must be an array")
        d["model_seeds"] = tuple(d["model_seeds"])
    return BuildTrainingConfig(**d)


def supervision_projection(data):
    result={"task_sha256": data["task_sha256"],
            "goals": [{"deck": r["deck"], "label": r["label"], "source": r["source"],
                       "evidence_status": r["evidence"]["status"],
                       "trajectory_sha256": r["evidence"].get("trajectory_sha256",r["evidence"].get('native_route',{}).get('trajectory_sha256'))} for r in data["goals"]],
            "pairs": data["pairs"]}
    if 'purpose' in data:result['purpose']=data['purpose']
    return result


def validate_supervision(task, assets, data):
    from .semantic_training import SOURCE as semantic_source,validate as validate_semantic
    if isinstance(data,dict) and data.get('source')==semantic_source:
        return validate_semantic(task,assets,data)
    fields(data, {"source", "task_sha256", "goals", "pairs", "supervision_sha256", "unknown_routes_used_as_negative",
                  "competitive_quality_labels", "public_effect_receipts"})
    if (data["source"] not in ("engineering_fixture", "engineering_real_game_pair_v1") or data["task_sha256"] != task.sha256
            or data["unknown_routes_used_as_negative"] is not False or data["competitive_quality_labels"] is not False):
        raise ContractError("building supervision source/goal/label boundary differs")
    integer(len(array(data["goals"], "goal records")), "goal record count", 1, 16)
    integer(len(array(data["pairs"], "optimization pairs")), "pair count", 1, 8)
    for record in data["goals"]:
        fields(record, {"deck", "label", "source", "evidence"})
        deck = DeckParts.from_dict(record["deck"])
        if type(record["label"]) not in (int, float) or record["label"] not in (0, 1):
            raise ContractError("goal supervision must be binary verified/failure labels")
        proof = record["evidence"]
        if record["label"] == 1:
            fields(proof, {"status", "card_list_legal", "task_sha256", "deck_sha256", "starting_condition", "random_dependency",
                           "core_attempts", "responses", "core_event_kinds", "trajectory_sha256", "elapsed_seconds", "unmet"}, {"route_evidence"})
            assets.validate(task, deck)
            if (record["source"] != "real_core_conditional_goal" or proof["status"] != "verified_success"
                    or proof["task_sha256"] != task.sha256 or proof["deck_sha256"] != digest(deck.to_dict())
                    or proof["starting_condition"] != task.goal["starting_conditions"]
                    or (61 if task.goal["kind"] == "normal_summon" else 63) not in proof["core_event_kinds"]
                    or digest(proof["responses"]) != proof["trajectory_sha256"]):
                raise ContractError("positive goal record lacks consistent conditional core evidence")
            if task.goal["kind"] != "normal_summon":
                from .contracts import Observation
                from .extra_routes import completed_special_summon
                evidence = fields(proof.get("route_evidence"), {"driver", "opponent", "conditional_only", "material_preference",
                                                              "sum_choices", "final_observation", "core_event_audit_not_policy_input", "versions"}, {"exploration", "private_selection_key_audit_only"})
                from .extra_routes import route_selection_key
                route_selection_key(assets,deck,evidence)
                if (evidence["conditional_only"] is not True or evidence["versions"] != task.environment["versions"]
                        or not completed_special_summon(evidence["core_event_audit_not_policy_input"],
                                                       Observation.from_dict(evidence["final_observation"]), 0, task.goal["card_id"])):
                    raise ContractError("extra goal lacks its own completed real-core route")
        else:
            fields(proof, {"status", "reason"})
            if record["source"] != "explicit_hard_constraint_failure" or proof["status"] != "hard_constraint_failure":
                raise ContractError("unknown/unsupported routes cannot become negative goal labels")
            try:
                assets.validate(task, deck)
            except ContractError:
                pass
            else:
                raise ContractError("negative goal record does not actually fail hard constraints")
    for pair in data["pairs"]:
        fields(pair, {"better", "worse", "better_value", "worse_value", "source", "hard_constraints_checked"}, {"evidence"})
        better, worse = [DeckParts.from_dict(pair[k]) for k in ("better", "worse")]
        assets.validate(task, better)
        assets.validate(task, worse)
        if data["source"] == "engineering_fixture":
            if (pair["source"] != "engineering_mean_printed_attack_proxy_only" or "evidence" in pair
                    or pair["hard_constraints_checked"] is not True or pair["better_value"] != engineering_proxy(better, assets)
                    or pair["worse_value"] != engineering_proxy(worse, assets) or pair["better_value"] <= pair["worse_value"]):
                raise ContractError("engineering optimization proxy comparison is invalid")
        else:
            from .build_feedback import SOURCE, validate_comparison
            comparison = pair.get("evidence")
            candidates = validate_comparison(task, assets, comparison)
            preferred = comparison["preferred_index"]
            if (pair["source"] != SOURCE or comparison["plan"]["purpose"] != "construction_train" or preferred is None
                    or pair["hard_constraints_checked"] is not True or better != candidates[preferred] or worse != candidates[1-preferred]
                    or pair["better_value"] != comparison["mean_scores"][preferred] or pair["worse_value"] != comparison["mean_scores"][1-preferred]):
                raise ContractError("real optimization comparison is tied, mismatched or not training data")
    if digest(supervision_projection(data)) != data["supervision_sha256"]:
        raise ContractError("building supervision fingerprint differs")


def engineering_dataset(task, assets):
    if task.source != "engineering_fixture":
        raise ContractError("CPU fixture training cannot relabel a user task as engineering data")
    candidates = goal_candidates(task, assets)[:2]
    if len(candidates) < 2:
        raise ContractError("engineering goal proof needs two distinct legal candidates")
    goals = []
    for deck in candidates:
        proof = verify_goal(task, deck, assets)
        if proof["status"] != "verified_success":
            raise ContractError("route not verified; unknown/unsupported is not a negative training label")
        goals.append({"deck": deck.to_dict(), "label": 1., "source": "real_core_conditional_goal", "evidence": proof})
        bad = DeckParts(deck.main[:-1], deck.extra, deck.side)
        try:
            assets.validate(task, bad)
        except ContractError:
            goals.append({"deck": bad.to_dict(), "label": 0., "source": "explicit_hard_constraint_failure",
                          "evidence": {"status": "hard_constraint_failure", "reason": "main size differs from task"}})
        else:
            raise ContractError("negative engineering example unexpectedly satisfies constraints")
    choices = edit_candidates(task, assets, candidates[0])
    ordered = sorted(choices, key=lambda d: (engineering_proxy(d, assets), digest(d.to_dict())))
    pairs = []
    for worse in ordered[:2]:
        better = ordered[-1]
        if engineering_proxy(better, assets) <= engineering_proxy(worse, assets):
            continue
        pairs.append({"better": better.to_dict(), "worse": worse.to_dict(),
                      "better_value": engineering_proxy(better, assets), "worse_value": engineering_proxy(worse, assets),
                      "source": "engineering_mean_printed_attack_proxy_only", "hard_constraints_checked": True})
    if not pairs:
        raise ContractError("engineering comparison has no strict proxy difference")
    data = {"source": "engineering_fixture", "task_sha256": task.sha256, "goals": goals, "pairs": pairs,
            "unknown_routes_used_as_negative": False, "competitive_quality_labels": False,
            "public_effect_receipts": assets.effect_receipts(task)}
    data["supervision_sha256"] = digest(supervision_projection(data))
    validate_supervision(task, assets, data)
    return data


class BuildTrainer:
    def __init__(self, task, assets, config, *, device="cpu"):
        self.device = resolve_device(device)
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        random.seed(config.batch_seed)
        self.task, self.config = task, config
        self.encoder = BuildEncoder(task, assets, config.model)
        self.models, self.optimizers, self.schedulers = {}, {}, {}
        for role, seed in zip(ROLES, config.model_seeds):
            torch.manual_seed(seed)
            model = BuildRanker(config.model, len(self.encoder.card_ids), len(self.encoder.tags)).to(self.device)
            self.models[role] = model
            self.optimizers[role] = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=0., foreach=False, fused=False)
            self.schedulers[role] = torch.optim.lr_scheduler.StepLR(self.optimizers[role], 1, .99)
        pointers = [{p.data_ptr() for p in self.models[r].parameters()} for r in ROLES]
        if pointers[0] & pointers[1]:
            raise ContractError("building roles share trainable storage")
        self.batch_rng = torch.Generator(device="cpu").manual_seed(config.batch_seed)
        self.updates, self.batch_cursor = {role: 0 for role in ROLES}, 0

    def _apply(self, role, loss):
        model, optimizer = self.models[role], self.optimizers[role]
        if not torch.isfinite(loss):
            raise ContractError("non-finite building loss")
        previous_hash = parameter_digest(model)
        before = {name: p.detach().clone() for name, p in model.named_parameters()}
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), .5, error_if_nonfinite=True))
        optimizer.step()
        self.schedulers[role].step()
        changed = sum(int(torch.count_nonzero(before[n] != p.detach())) for n, p in model.named_parameters())
        delta = math.sqrt(sum(float(((before[n] - p.detach()) ** 2).sum()) for n, p in model.named_parameters()))
        head_delta = math.sqrt(sum(float(((before[n] - p.detach()) ** 2).sum()) for n, p in model.named_parameters() if n.startswith("head.")))
        if not changed or not norm or not head_delta:
            raise ContractError("no actual building parameter/head update")
        self.updates[role] += 1
        return {"role": role, "optimizer_step": self.updates[role], "loss": float(loss.detach()),
                "gradient_norm_before_clip": norm, "changed_parameter_elements": changed,
                "parameter_delta_l2": delta, "head_delta_l2": head_delta,
                "before_sha256": previous_hash, "after_sha256": parameter_digest(model),
                "learning_rate_next": optimizer.param_groups[0]["lr"]}

    def step(self, data,*,data_admission=None):
        if self.batch_cursor >= self.config.batches:
            raise ContractError("building supervision identity/budget differs")
        validate_supervision(self.task, self.encoder.assets, data)
        from .semantic_training import SOURCE as semantic_source
        if data['source']==semantic_source:
            from .data_isolation import ConstructionAdmission
            if not isinstance(data_admission,ConstructionAdmission):raise ContractError('semantic model updates require indexed training data admission')
            data_admission.assert_data(self.task,data)
        results = []
        for role in ROLES:
            self.models[role].train()
            records = data["goals"] if role == "build_goal" else data["pairs"]
            order = torch.randperm(len(records), generator=self.batch_rng).tolist()
            if role == "build_goal":
                records = [records[i] for i in order]
                decks = [DeckParts.from_dict(r["deck"]) for r in records]
                scores = self.models[role](self.encoder.batch(self.task, decks))
                loss = F.binary_cross_entropy_with_logits(scores, torch.tensor([r["label"] for r in records], device=self.device))
            else:
                pairs = [records[i] for i in order]
                decks = [DeckParts.from_dict(r[part]) for r in pairs for part in ("better", "worse")]
                scores = self.models[role](self.encoder.batch(self.task, decks)).reshape(-1, 2)
                loss = F.softplus(scores[:, 1] - scores[:, 0]).mean()
            results.append(self._apply(role, loss))
        self.batch_cursor += 1
        return results


def binding_for(task, assets, data):
    code = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        code.update(path.name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return {"source_commits": assets.receipt["source_commits"], "resources": assets.receipt["resources"],
            "python": platform.python_version(), "torch": str(torch.__version__), "feature_version": FEATURE_VERSION,
            "python_implementation_sha256": code.hexdigest(), "task_sha256": task.sha256,
            "supervision_sha256": data["supervision_sha256"]}


def save_checkpoint(trainer, directory, checkpoint_id, binding, *, allow_initial=False):
    identifier(checkpoint_id)
    initial = allow_initial is True and trainer.batch_cursor == 0 and all(n == 0 for n in trainer.updates.values())
    if not initial and (trainer.batch_cursor < 1 or any(n != trainer.batch_cursor for n in trainer.updates.values())):
        raise ContractError("paired building checkpoint requires completed role-update boundary")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{checkpoint_id}.weights"
    state = {"schema_version": 1, "kind": "paired-building-cpu", "boundary": "initial" if initial else "complete-role-update-batch",
             "config": asdict(trainer.config), "task": trainer.task.to_dict(), "binding": binding,
             "execution": execution_metadata(trainer.device), "device_rng": capture_device_rng(trainer.device),
             "vocabulary_sha256": trainer.encoder.vocabulary_sha256, "updates": trainer.updates,
             "batch_cursor": trainer.batch_cursor,
             "models": {r: trainer.models[r].state_dict() for r in ROLES},
             "model_hashes": {r: parameter_digest(trainer.models[r]) for r in ROLES},
             "optimizers": {r: trainer.optimizers[r].state_dict() for r in ROLES},
             "schedulers": {r: trainer.schedulers[r].state_dict() for r in ROLES},
             "rng": {"torch": torch.get_rng_state(), "python": random.getstate(), "batch": trainer.batch_rng.get_state()}}
    with path.open("xb") as handle:
        torch.save(state, handle)
    return path


def load_checkpoint(path, assets, expected_binding, *, allow_initial=False, device=None):
    state = torch.load(path, map_location="cpu", weights_only=True)
    fields(state, {"schema_version", "kind", "boundary", "config", "task", "binding", "vocabulary_sha256", "updates", "batch_cursor",
                   "models", "model_hashes", "optimizers", "schedulers", "rng"}, {"execution", "device_rng"})
    integer(state["schema_version"], "building checkpoint schema", 1, 1)
    initial = allow_initial is True and state["boundary"] == "initial" and state["batch_cursor"] == 0
    restored_config = config_from_dict(state["config"])
    integer(state["batch_cursor"], "building checkpoint cursor", 0 if initial else 1, restored_config.batches)
    if state["kind"] != "paired-building-cpu" or (state["boundary"] != "complete-role-update-batch" and not initial) or state["binding"] != expected_binding:
        raise ContractError("building checkpoint boundary/resources differ")
    task = BuildTask.from_dict(state["task"])
    if task.sha256 != expected_binding["task_sha256"]:
        raise ContractError("checkpoint goal identity differs")
    if binding_for(task, assets, {"supervision_sha256": expected_binding["supervision_sha256"]}) != expected_binding:
        raise ContractError("current building resources/implementation differ from checkpoint")
    trainer = BuildTrainer(task, assets, restored_config, device=checkpoint_execution(state, device))
    for role in ROLES:
        integer(state["updates"][role], "building role updates", state["batch_cursor"], state["batch_cursor"])
        trainer.models[role].load_state_dict(state["models"][role], strict=True)
        trainer.optimizers[role].load_state_dict(state["optimizers"][role])
        optimizer_to(trainer.optimizers[role], trainer.device)
        trainer.schedulers[role].load_state_dict(state["schedulers"][role])
        if parameter_digest(trainer.models[role]) != state["model_hashes"][role]:
            raise ContractError("building checkpoint parameter checksum differs")
    if trainer.encoder.vocabulary_sha256 != state["vocabulary_sha256"]:
        raise ContractError("building checkpoint vocabulary differs")
    trainer.updates, trainer.batch_cursor = state["updates"], state["batch_cursor"]
    torch.set_rng_state(state["rng"]["torch"])
    trainer.batch_rng.set_state(state["rng"]["batch"])
    random.setstate(state["rng"]["python"])
    if "device_rng" in state: restore_device_rng(state["device_rng"], trainer.device)
    return trainer


def run_build_training_smoke(root, state_root, run_id, task, config=None):
    identifier(run_id)
    state_root = Path(state_root).resolve()
    run = state_root / "runs" / run_id
    if run.exists():
        raise ContractError("building run already exists; choose a new run ID")
    assets, config = BuildAssets(root), config or BuildTrainingConfig()
    trainer = BuildTrainer(task, assets, config)
    reporter = RunReporter(state_root)
    snapshot = {"schema_version": 1, "run_id": run_id, "state": "running", "revision": 0,
                "model_versions": {"build_goal": "cpu-goal-prototype-v1", "build_optimizer": "cpu-optimizer-prototype-v1"},
                "metrics": reporter.resources(), "checkpoint_ids": [], "source": "trainer"}
    reporter.publish(snapshot)
    checkpoints, updates = [], []

    def publish(state):
        metrics = dict(reporter.resources(), steps=sum(trainer.updates.values()))
        if updates:
            metrics["loss"] = sum(u["loss"] for u in updates[-1]) / 2
        old = reporter.snapshot(run_id)
        reporter.publish(dict(old, state=state, revision=old["revision"] + 1,
                              checkpoint_ids=[c["checkpoint_id"] for c in checkpoints], metrics=metrics))
        return metrics

    try:
        admission = None
        semantic = task.goal['kind']=='deck_constraints'
        if semantic:
            from .semantic_training import dataset
            from .data_isolation import DataIndex
            data=dataset(task,assets)
            index=DataIndex(run/'private-data')
            index.freeze({'dataset_id':'construction-train','experiment_id':run_id,'purpose':'train','family':'construction',
                          'versions':task.environment['versions'],'opponents':[],'task_sha256':task.sha256})
            index.ingest_construction('construction-train','construction-labels',task,assets,data,seeds=())
            admission=index.admit_construction('construction-labels',task,data)
        else:data = engineering_dataset(task, assets)
        binding = binding_for(task, assets, data)
        (run / "supervision.json").write_text(canonical_json(data) + "\n")
        first = None
        for batch in range(1, 3):
            updates.append(trainer.step(data,data_admission=admission))
            name = f"batch-{batch}"
            path = save_checkpoint(trainer, run / "checkpoints", name, binding)
            first = path if batch == 1 else first
            meta = {"schema_version": 1, "run_id": run_id, "checkpoint_id": name, "artifact_bytes": path.stat().st_size,
                    "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "step": batch}
            path.with_suffix(".json").write_text(canonical_json(meta) + "\n")
            checkpoints.append(meta)
            publish("running")
            RunMonitor(state_root).checkpoint(run_id, name)
        recovered = load_checkpoint(first, assets, binding)
        repeat = recovered.step(data,data_admission=admission)
        verified = (repeat == updates[-1] and all(parameter_digest(trainer.models[r]) == parameter_digest(recovered.models[r]) for r in ROLES))
        if not verified:
            raise ContractError("actual building continuation diverged")
        alternation = alternate_build(task, assets, trainer.models, trainer.encoder)
        if len(alternation["stages"]) != 4:
            raise ContractError("four actual goal/optimizer stages not verified")
        metrics = publish("running")
        result = {"schema_version": 1, "ok": True, "scope": "bounded-goal-optimizer-cpu-engineering",
                  "source": ("actual-transformer-updates-and-combined-native-objectives" if 'route_goal' in task.goal else "actual-transformer-updates-and-catalog-constraints") if semantic else "actual-transformer-updates-and-real-core-goal-checks",
                  "task": task.to_dict(), "binding": binding, "training_config": asdict(config),
                  "parameter_counts": {r: sum(p.numel() for p in trainer.models[r].parameters()) for r in ROLES},
                  "independent_weights": True, "updates": updates, "canonical_updates_per_role": 2,
                  "canonical_optimizer_calls": 4, "physical_optimizer_calls_including_recovery": 6,
                  "restore_verified": verified, "checkpoints": checkpoints, "metrics": metrics,
                  "alternation": alternation, "supervision": data,
                  "hardware": {"device": "cpu", "torch_threads": 1, "processor": cpu_name(), "cuda_build": torch.version.cuda,
                               "platform": platform.platform(), "logical_cpu_count": os.cpu_count(),
                               "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None},
                  "cost": {"new_paid_instances_started": 0, "external_api_calls": 0, "cloud_development_cpu_cost": "not-exposed"},
                  "competitive_construction_quality_validated": False, "models_in_this_run": list(ROLES),
                  "coordinator_training_in_this_run": False}
        if semantic:result['data_index']=index.summary()
        (run / "proof.json").write_text(canonical_json(result) + "\n")
        publish("completed")
        return result
    except Exception:
        publish("failed")
        raise
