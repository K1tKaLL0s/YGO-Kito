"""Small scoped coordinator behind deterministic permissions and hard limits.

Legacy advice remains explicit. Scoped control/forecast and budget supervision
are executable; useful decisions and statistical calibration require training.
"""

from dataclasses import asdict, dataclass
import math

import torch
from torch import nn
from torch.nn import functional as F

from .build_contracts import digest
from .agent_registry import identifier
from .coord_contracts import ROUTES, rule_route
from .duel_model import parameter_digest
from .device import (resolve_device, model_device, move_batch, execution_metadata,
                     checkpoint_execution, optimizer_to, capture_device_rng, restore_device_rng)
from .validation import ContractError, fields, integer
from .effect_records import SUMMARY_WIDTH, SUMMARY_VERSION

FEATURE_VERSION = "coordinator-public-scope-context-v2"
MECHANISM_FEATURE_VERSION = "coordinator-public-mechanism-context-v3"
SCOPE_WIDTH = 64
MECHANISM_SCOPE_WIDTH = 2 * SUMMARY_WIDTH


def scope_tensor(value):
    if (not isinstance(value, list) or len(value) != SCOPE_WIDTH or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in value)):
        raise ContractError("coordinator requires 64 finite public scope features")
    return [float(x) for x in value]


def mechanism_tensor(value):
    if (not isinstance(value, list) or len(value) != MECHANISM_SCOPE_WIDTH or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in value)):
        raise ContractError('coordinator requires finite versioned mechanism features')
    return [float(x) for x in value]


def scope_input(value):
    """Legacy 64-vector or explicit v3 input; never reinterpret old slots."""
    if isinstance(value, list):
        return scope_tensor(value), None
    fields(value, {'feature_version', 'summary_version', 'scope_features', 'mechanism_features'})
    if value['feature_version'] != MECHANISM_FEATURE_VERSION or value['summary_version'] != SUMMARY_VERSION:
        raise ContractError('coordinator mechanism input version differs')
    return scope_tensor(value['scope_features']), mechanism_tensor(value['mechanism_features'])


def public_scope_features(builder, task, deck, scope, opponent_decks):
    """Reuse public build facts, retaining exact task/deck/actor/environment identity.

    No outcomes or hidden state enter this pre-game representation. Hash bytes
    distinguish otherwise equal numeric summaries; they are not a strength label.
    """
    from .coord_contracts import evaluation_scope, FeedbackPolicy
    from .build_contracts import DeckParts
    scope = evaluation_scope(scope, {"task": task.to_dict()}, FeedbackPolicy())
    _, numbers, state = builder.encoder.encode(task, deck)
    rows = list(zip(*numbers))
    values = list(state) + [sum(r) / len(r) for r in rows] + [max(r) for r in rows]
    facts = [0.] * 6
    for opponent in scope["opponents"]:
        other = opponent_decks[opponent["opponent_id"]]
        if not isinstance(other, DeckParts) or digest(other.to_dict()) != opponent["deck_sha256"]:
            raise ContractError("predictor opponent deck differs from frozen scope")
        cards = other.main + other.extra + other.side
        if not cards:
            raise ContractError("predictor needs the concrete opponent deck")
        for code in cards:
            row = builder.encoder.assets.facts(code)
            if len(row) != 6:
                raise ContractError("public build facts schema differs")
            for i, x in enumerate(row):
                facts[i] += x * opponent["weight"] / len(cards)
    values += facts + scope["initiative_weights"] + [float(scope["unit"] == u) for u in ("BO1", "BO3")]
    for identity, size in ((scope["actor_policy_sha256"], 8), (digest(scope["versions"]), 4),
                           (task.sha256, 4), (digest(deck.to_dict()), 8), (digest(scope["opponents"]), 4)):
        values.extend(b / 255 for b in bytes.fromhex(identity)[:size])
    return scope_tensor(values)


def public_scope_input(builder, task, deck, scope, opponent_decks):
    """Supplement old public features with own/weighted-opponent mechanisms.

    Inputs are concrete registered public decks, never live hidden observations
    or reference-construction labels. Callers opt into a new coordinator state.
    """
    legacy = public_scope_features(builder, task, deck, scope, opponent_decks)
    own = builder.encoder.public_mechanism_summary(deck)
    other = [0.] * SUMMARY_WIDTH
    for opponent in scope['opponents']:
        summary = builder.encoder.public_mechanism_summary(opponent_decks[opponent['opponent_id']])
        for i, value in enumerate(summary):
            other[i] += value * opponent['weight']
    return {'feature_version': MECHANISM_FEATURE_VERSION, 'summary_version': SUMMARY_VERSION,
            'scope_features': legacy, 'mechanism_features': mechanism_tensor(own + other)}


def context_tensor(context):
    rule_route(context)  # Strict aggregate fields; no engine handle, deck order or hand.
    flags = [float(context[k]) for k in ("goal_valid", "card_list_valid", "has_forecast", "warning", "rebuild_required", "operation_error", "system_error")]
    mean, forecast = context["score_mean"], context["forecast"]
    return flags + [min(context["remaining_tasks"], 100) / 100, min(context["completed_matches"], 1000) / 1000,
                    mean or 0., float(mean is not None), forecast or 0., float(forecast is not None),
                    forecast - mean if forecast is not None and mean is not None else 0.]


def engineering_examples():
    base = {"goal_valid": True, "card_list_valid": True, "has_forecast": True, "warning": False, "rebuild_required": False,
            "operation_error": False, "system_error": False, "remaining_tasks": 1, "completed_matches": 0, "score_mean": None, "forecast": .5}
    changes = ({"goal_valid": False}, {"warning": True, "completed_matches": 50, "score_mean": .1},
               {"has_forecast": False, "forecast": None}, {}, {"operation_error": True}, {"system_error": True},
               {"remaining_tasks": 0}, {"rebuild_required": True, "completed_matches": 125, "score_mean": .1, "forecast": .9})
    records = [{"context": dict(base, **change), "route_label": rule_route(dict(base, **change))[0],
                "synthetic_probability_anchor": anchor} for change, anchor in zip(changes, (.2, .3, .5, .5, .25, .2, .5, .2))]
    return {"source": "synthetic_rule_imitation_and_probability_anchors", "records": records,
            "real_win_rate_supervision": False, "sha256": digest(records)}


def supervision_rows(examples):
    """Validate explicit host labels; provenance hashes do not certify truth."""
    fields(examples, {"source", "records", "real_win_rate_supervision", "sha256"})
    if examples["source"] == engineering_examples()["source"]:
        if examples != engineering_examples():
            raise ContractError("coordinator engineering supervision differs")
        return examples["records"], True
    if examples["source"] != "host_logged_supervision_v1" or examples["real_win_rate_supervision"] is not False:
        raise ContractError("explicit host labels cannot claim verified real win-rate supervision")
    rows = examples["records"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096 or examples["sha256"] != digest(rows):
        raise ContractError("coordinator logged supervision size/digest differs")
    seen = set()
    for row in rows:
        fields(row, {"context", "route_label", "forecast_target", "provenance"}, {"scope_features", "budget_target"})
        context_tensor(row["context"])
        if row["route_label"] is not None and row["route_label"] not in ROUTES:
            raise ContractError("unknown logged route target")
        if "scope_features" in row:
            scope_input(row["scope_features"])
        if "budget_target" in row:
            target_budget = row["budget_target"]
            if type(target_budget) not in (int, float) or not math.isfinite(target_budget) or not 0 <= target_budget <= 1:
                raise ContractError("logged budget target must be a fraction within [0,1]")
            if "scope_features" not in row:
                raise ContractError("budget supervision needs concrete public scope features")
        target = row["forecast_target"]
        if target is not None and (type(target) not in (int, float) or not math.isfinite(target) or not 0 <= target <= 1):
            raise ContractError("logged forecast target must be finite in [0,1] or absent")
        provenance = fields(row["provenance"], {"dataset_id", "record_id", "source", "evidence_sha256"})
        identifier(provenance["dataset_id"]); identifier(provenance["record_id"])
        if not isinstance(provenance["source"], str) or not provenance["source"].strip() or len(provenance["source"]) > 256:
            raise ContractError("logged target provenance source required")
        from .coord_contracts import sha256
        sha256(provenance["evidence_sha256"])
        ident = (provenance["dataset_id"], provenance["record_id"])
        if ident in seen:
            raise ContractError("duplicate logged supervision record")
        seen.add(ident)
    return rows, False


@dataclass(frozen=True)
class CoordinatorModelConfig:
    hidden: int = 16
    model_seed: int = 1357
    batch_seed: int = 2468
    learning_rate: float = .003
    steps: int = 2
    mechanism_inputs: bool = False

    def __post_init__(self):
        if type(self.mechanism_inputs) is not bool:
            raise ContractError('coordinator mechanism input opt-in must be boolean')
        integer(self.hidden, "coordinator hidden width", 4, 64)
        integer(self.model_seed, "coordinator model seed", 0, 2**32 - 8)
        integer(self.batch_seed, "coordinator batch seed", 0, 2**32 - 8)
        integer(self.steps, "coordinator updates", 1, 100000)
        if type(self.learning_rate) not in (int, float) or not math.isfinite(self.learning_rate) or not 0 < self.learning_rate <= .01:
            raise ContractError("coordinator learning rate outside CPU proof range")


class CoordinatorNetwork(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(14, config.hidden), nn.Tanh(), nn.Linear(config.hidden, config.hidden), nn.Tanh())
        self.route_head = nn.Linear(config.hidden, len(ROUTES))
        self.forecast_head = nn.Linear(config.hidden, 1)
        self.scope_projection = nn.Linear(SCOPE_WIDTH, config.hidden, bias=False)
        self.budget_head = nn.Linear(config.hidden, 1)
        if config.mechanism_inputs:
            # Appended only for a new explicit architecture. A zero extension
            # preserves legacy predictions before any mechanism supervision.
            self.mechanism_projection = nn.Linear(MECHANISM_SCOPE_WIDTH, config.hidden, bias=False)
            nn.init.zeros_(self.mechanism_projection.weight)

    def forward(self, values):
        values = move_batch(values, model_device(self))
        if values.ndim != 2 or values.shape[1] != 14 or not torch.isfinite(values).all():
            raise ContractError("coordinator requires finite CPU aggregate features")
        hidden = self.encoder(values)
        return self.route_head(hidden), self.forecast_head(hidden).squeeze(-1).sigmoid()

    def forward_scoped(self, values, scope_values, mechanism_values=None):
        values, scope_values, mechanism_values = move_batch((values, scope_values, mechanism_values), model_device(self))
        if (values.ndim != 2 or values.shape[1] != 14 or scope_values.shape != (len(values), SCOPE_WIDTH)
                or not torch.isfinite(values).all() or not torch.isfinite(scope_values).all()):
            raise ContractError("invalid aggregate/public-scope batch")
        hidden = self.encoder(values) + self.scope_projection(scope_values).tanh()
        if mechanism_values is not None:
            if (not hasattr(self, 'mechanism_projection') or mechanism_values.shape != (len(values), MECHANISM_SCOPE_WIDTH)
                    or not torch.isfinite(mechanism_values).all()):
                raise ContractError('mechanism input requires the explicit v3 coordinator architecture')
            hidden = hidden + self.mechanism_projection(mechanism_values).tanh()
        return (self.route_head(hidden), self.forecast_head(hidden).squeeze(-1).sigmoid(),
                self.budget_head(hidden).squeeze(-1).sigmoid())


class CoordinatorTrainer:
    def __init__(self, config=None, *, device="cpu"):
        self.config = config or CoordinatorModelConfig()
        self.device = resolve_device(device)
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(self.config.model_seed)
        self.model = CoordinatorNetwork(self.config).to(self.device)
        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=self.config.learning_rate, weight_decay=0., foreach=False, fused=False)
        self.scheduler = torch.optim.lr_scheduler.StepLR(self.optimizer, 1, .99)
        self.batch_rng = torch.Generator(device="cpu").manual_seed(self.config.batch_seed)
        self.updates = 0

    def step(self, examples=None):
        examples = engineering_examples() if examples is None else examples
        rows, synthetic = supervision_rows(examples)
        if self.updates >= self.config.steps:
            raise ContractError("coordinator update budget exhausted")
        order = torch.randperm(len(rows), generator=self.batch_rng).tolist()
        values = torch.tensor([context_tensor(rows[i]["context"]) for i in order])
        routed = [j for j, i in enumerate(order) if rows[i]["route_label"] is not None]
        routes = torch.tensor([ROUTES.index(rows[order[j]]["route_label"]) for j in routed], device=self.device)
        targets = [rows[i]["synthetic_probability_anchor" if synthetic else "forecast_target"] for i in order]
        labelled = [i for i, target in enumerate(targets) if target is not None]
        self.model.train()
        scoped = any("scope_features" in r for r in rows)
        if scoped:
            inputs = [scope_input(rows[i].get('scope_features', [0.] * SCOPE_WIDTH)) for i in order]
            scope_values = torch.tensor([item[0] for item in inputs])
            mechanisms = (torch.tensor([item[1] if item[1] is not None else [0.] * MECHANISM_SCOPE_WIDTH for item in inputs])
                          if any(item[1] is not None for item in inputs) else None)
            logits, predictions, allocations = self.model.forward_scoped(values, scope_values, mechanisms)
        else:
            logits, predictions = self.model(values)
        route_loss = F.cross_entropy(logits[routed], routes) if routed else logits.sum() * 0
        forecast_loss = (F.mse_loss(predictions[labelled], torch.tensor([targets[i] for i in labelled], device=self.device))
                         if labelled else logits.sum() * 0)
        budget_rows = [j for j, i in enumerate(order) if "budget_target" in rows[i]]
        budget_loss = (F.mse_loss(allocations[budget_rows], torch.tensor([rows[order[j]]["budget_target"] for j in budget_rows], device=self.device))
                       if budget_rows else logits.sum() * 0)
        loss = route_loss + forecast_loss + budget_loss
        before_hash = parameter_digest(self.model)
        before = {n: p.detach().clone() for n, p in self.model.named_parameters()}
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        for head, active in ((self.model.route_head, routed), (self.model.forecast_head, labelled), (self.model.budget_head, budget_rows)):
            if not active:
                for parameter in head.parameters():
                    parameter.grad = None  # Do not move an unlabelled head through old momentum.
        norm = float(torch.nn.utils.clip_grad_norm_(self.model.parameters(), .5, error_if_nonfinite=True))
        self.optimizer.step()
        self.scheduler.step()
        deltas = {n: float(((p.detach() - before[n]) ** 2).sum()) for n, p in self.model.named_parameters()}
        changed = sum(int(torch.count_nonzero(p.detach() != before[n])) for n, p in self.model.named_parameters())
        if not changed or not norm or (routed and not any(v for n, v in deltas.items() if n.startswith("route_head"))) or (labelled and not any(v for n, v in deltas.items() if n.startswith("forecast_head"))):
            raise ContractError("coordinator model/heads did not actually update")
        self.updates += 1
        return {"optimizer_step": self.updates, "loss": float(loss.detach()), "route_loss": float(route_loss.detach()),
                "synthetic_forecast_loss": float(forecast_loss.detach()) if synthetic else None,
                "forecast_loss": float(forecast_loss.detach()) if labelled else None,
                "forecast_supervised_rows": len(labelled), "gradient_norm_before_clip": norm,
                "budget_supervised_rows": len(budget_rows), "budget_loss": float(budget_loss.detach()) if budget_rows else None,
                "changed_parameter_elements": changed, "parameter_delta_l2": math.sqrt(sum(deltas.values())),
                "before_sha256": before_hash, "after_sha256": parameter_digest(self.model),
                "supervision_source": examples["source"], "supervision_sha256": examples["sha256"],
                "supervision_evidence_verified": False, "real_win_rate_supervision": False, "calibration": "pending"}

    def advice(self, context):
        self.model.eval()
        with torch.no_grad():
            logits, forecast = self.model(torch.tensor([context_tensor(context)]))
        return {"route": ROUTES[int(logits[0].argmax())], "probability": float(forecast[0]),
                "model_sha256": parameter_digest(self.model), "calibration": "pending", "mode": "advisory_only"}

    def control(self, context, features, *, allowed_routes, max_units):
        integer(max_units, "host cycle budget", 0, 10000)
        if not allowed_routes or any(r not in ROUTES for r in allowed_routes):
            raise ContractError("explicit eligible cycle routes required")
        self.model.eval()
        scope_values, mechanism_values = scope_input(features)
        with torch.no_grad():
            logits, forecast, allocation = self.model.forward_scoped(
                torch.tensor([context_tensor(context)]), torch.tensor([scope_values]),
                torch.tensor([mechanism_values]) if mechanism_values is not None else None)
        route = max(allowed_routes, key=lambda r: float(logits[0, ROUTES.index(r)]))
        units = 0 if route == "stop" or not max_units else max(1, min(max_units, math.ceil(float(allocation[0]) * max_units)))
        return {"route": route, "budget_units": units, "probability": float(forecast[0]),
                "model_sha256": parameter_digest(self.model), "features_sha256": digest(features),
                "calibration": "pending", "mode": "learned_control", "ability_verified": False}

    def forecast(self, context, features):
        return self.control(context, features, allowed_routes=("evaluate_duel",), max_units=1)

    @classmethod
    def upgrade_mechanism_state(cls, state, *, device=None):
        """Return a separate v3 state; preserve the supplied checkpoint intact."""
        from copy import deepcopy
        if state.get('feature_version') != FEATURE_VERSION:
            raise ContractError('mechanism upgrade requires a legacy v2 coordinator state')
        with torch.random.fork_rng():
            legacy = cls.restore(deepcopy(state), device=device)
            config = dict(asdict(legacy.config), mechanism_inputs=True)
            trainer = cls(CoordinatorModelConfig(**config), device=legacy.device)
        incompatible = trainer.model.load_state_dict(legacy.model.state_dict(), strict=False)
        if set(incompatible.missing_keys) != {'mechanism_projection.weight'} or incompatible.unexpected_keys:
            raise ContractError('unsupported coordinator architecture for explicit mechanism upgrade')
        optimizer = deepcopy(state['optimizer'])
        if len(optimizer['param_groups']) != 1:
            raise ContractError('unsupported coordinator optimizer groups for mechanism upgrade')
        if len(optimizer['param_groups'][0]['params']) != len(list(legacy.model.parameters())):
            raise ContractError('legacy coordinator optimizer ordering differs')
        previous = optimizer['param_groups'][0]['params']
        if len(set(previous)) != len(previous):
            raise ContractError('duplicate legacy coordinator optimizer parameter identifiers')
        previous.append(max(previous, default=-1) + 1)
        trainer.optimizer.load_state_dict(optimizer)
        optimizer_to(trainer.optimizer, trainer.device)
        trainer.scheduler.load_state_dict(state['scheduler'])
        trainer.batch_rng.set_state(state['batch_rng'])
        trainer.updates = legacy.updates
        migrated = trainer.state()
        if 'device_rng' in state:
            migrated['device_rng'] = deepcopy(state['device_rng'])
        return migrated, {'kind': 'explicit-coordinator-v2-to-v3-mechanisms',
            'parent_sha256': state['model_sha256'], 'model_sha256': migrated['model_sha256'],
            'new_untrained_parameters': ['mechanism_projection.weight'],
            'old_parameters_and_optimizer_moments_preserved': True,
            'projection_initialization': 'zero', 'training_executed': False, 'ability_verified': False}

    @classmethod
    def upgrade_aggregate_state(cls, state, *, device=None):
        """Explicit v1 -> v2 migration; never called by restore or a course run.

        Preserve every old tensor and Adam moment. Only the scope projection and
        budget head are newly initialized, with that fact in the returned receipt.
        The caller must bind/save a new course source/checkpoint generation.
        """
        from copy import deepcopy
        import hashlib
        if state.get("feature_version") != "coordinator-aggregate-context-v1":
            raise ContractError("explicit migration requires a v1 coordinator state")
        checksum = hashlib.sha256()
        for name, tensor in sorted(state["model"].items()):
            checksum.update(name.encode()); checksum.update(tensor.detach().cpu().contiguous().numpy().tobytes())
        if checksum.hexdigest() != state["model_sha256"]:
            raise ContractError("legacy coordinator checksum differs")
        with torch.random.fork_rng():
            trainer = cls(CoordinatorModelConfig(**state["config"]), device=checkpoint_execution(state, device))
        incompatible = trainer.model.load_state_dict(state["model"], strict=False)
        new_names = {"scope_projection.weight", "budget_head.weight", "budget_head.bias"}
        if set(incompatible.missing_keys) != new_names or incompatible.unexpected_keys:
            raise ContractError("legacy model is not the supported aggregate architecture")
        optimizer = deepcopy(state["optimizer"])
        if len(optimizer["param_groups"]) != 1:
            raise ContractError("unsupported legacy coordinator optimizer groups")
        optimizer["param_groups"][0]["params"] = trainer.optimizer.state_dict()["param_groups"][0]["params"]
        trainer.optimizer.load_state_dict(optimizer)
        optimizer_to(trainer.optimizer, trainer.device)
        trainer.scheduler.load_state_dict(state["scheduler"])
        trainer.batch_rng.set_state(state["batch_rng"])
        trainer.updates = integer(state["updates"], "legacy update cursor", 0, trainer.config.steps)
        migrated = trainer.state()
        if "device_rng" in state:
            migrated["device_rng"] = deepcopy(state["device_rng"])
        return migrated, {"kind": "explicit-coordinator-v1-to-v2", "parent_sha256": state["model_sha256"],
            "model_sha256": migrated["model_sha256"], "new_untrained_parameters": sorted(new_names),
            "old_parameters_and_optimizer_moments_preserved": True, "training_executed": False}

    def state(self):
        return {"config": asdict(self.config), "feature_version": MECHANISM_FEATURE_VERSION if self.config.mechanism_inputs else FEATURE_VERSION,
                "execution": execution_metadata(self.device), "device_rng": capture_device_rng(self.device),
                "model": self.model.state_dict(), "optimizer": self.optimizer.state_dict(), "scheduler": self.scheduler.state_dict(),
                "batch_rng": self.batch_rng.get_state(), "updates": self.updates, "model_sha256": parameter_digest(self.model)}

    @classmethod
    def restore(cls, state, *, device=None):
        fields(state, {"config", "feature_version", "model", "optimizer", "scheduler", "batch_rng", "updates", "model_sha256"}, {"execution", "device_rng"})
        config = CoordinatorModelConfig(**state['config'])
        expected_version = MECHANISM_FEATURE_VERSION if config.mechanism_inputs else FEATURE_VERSION
        if state["feature_version"] != expected_version:
            raise ContractError("coordinator feature version differs")
        trainer = cls(config, device=checkpoint_execution(state, device))
        trainer.model.load_state_dict(state["model"], strict=True)
        trainer.optimizer.load_state_dict(state["optimizer"])
        optimizer_to(trainer.optimizer, trainer.device)
        trainer.scheduler.load_state_dict(state["scheduler"])
        trainer.batch_rng.set_state(state["batch_rng"])
        integer(state["updates"], "restored coordinator updates", 0, trainer.config.steps)
        trainer.updates = state["updates"]
        if "device_rng" in state: restore_device_rng(state["device_rng"], trainer.device)
        if parameter_digest(trainer.model) != state["model_sha256"]:
            raise ContractError("coordinator checkpoint checksum differs")
        return trainer
