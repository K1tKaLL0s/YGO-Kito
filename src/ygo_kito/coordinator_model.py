"""Small learnable coordinator, advisory to the deterministic controller.

Training examples imitate engineering rules and synthetic probability anchors.
They do not establish a calibrated win-rate predictor or useful scheduling.
"""

from dataclasses import asdict, dataclass
import math

import torch
from torch import nn
from torch.nn import functional as F

from .build_contracts import digest
from .coord_contracts import ROUTES, rule_route
from .duel_model import parameter_digest
from .validation import ContractError, fields, integer

FEATURE_VERSION = "coordinator-aggregate-context-v1"


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


@dataclass(frozen=True)
class CoordinatorModelConfig:
    hidden: int = 16
    model_seed: int = 1357
    batch_seed: int = 2468
    learning_rate: float = .003
    steps: int = 2

    def __post_init__(self):
        integer(self.hidden, "coordinator hidden width", 4, 64)
        integer(self.model_seed, "coordinator model seed", 0, 2**32 - 8)
        integer(self.batch_seed, "coordinator batch seed", 0, 2**32 - 8)
        integer(self.steps, "coordinator proof updates", 2, 2)
        if type(self.learning_rate) not in (int, float) or not math.isfinite(self.learning_rate) or not 0 < self.learning_rate <= .01:
            raise ContractError("coordinator learning rate outside CPU proof range")


class CoordinatorNetwork(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(14, config.hidden), nn.Tanh(), nn.Linear(config.hidden, config.hidden), nn.Tanh())
        self.route_head = nn.Linear(config.hidden, len(ROUTES))
        self.forecast_head = nn.Linear(config.hidden, 1)

    def forward(self, values):
        if values.device.type != "cpu" or values.ndim != 2 or values.shape[1] != 14 or not torch.isfinite(values).all():
            raise ContractError("coordinator requires finite CPU aggregate features")
        hidden = self.encoder(values)
        return self.route_head(hidden), self.forecast_head(hidden).squeeze(-1).sigmoid()


class CoordinatorTrainer:
    def __init__(self, config=None):
        self.config = config or CoordinatorModelConfig()
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(self.config.model_seed)
        self.model = CoordinatorNetwork(self.config)
        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=self.config.learning_rate, weight_decay=0., foreach=False, fused=False)
        self.scheduler = torch.optim.lr_scheduler.StepLR(self.optimizer, 1, .99)
        self.batch_rng = torch.Generator(device="cpu").manual_seed(self.config.batch_seed)
        self.updates = 0

    def step(self, examples):
        fields(examples, {"source", "records", "real_win_rate_supervision", "sha256"})
        if (examples != engineering_examples() or self.updates >= self.config.steps):
            raise ContractError("coordinator fixture supervision/budget differs")
        rows = examples["records"]
        order = torch.randperm(len(rows), generator=self.batch_rng).tolist()
        values = torch.tensor([context_tensor(rows[i]["context"]) for i in order])
        routes = torch.tensor([ROUTES.index(rows[i]["route_label"]) for i in order])
        anchors = torch.tensor([rows[i]["synthetic_probability_anchor"] for i in order])
        self.model.train()
        logits, predictions = self.model(values)
        route_loss, forecast_loss = F.cross_entropy(logits, routes), F.mse_loss(predictions, anchors)
        loss = route_loss + forecast_loss
        before_hash = parameter_digest(self.model)
        before = {n: p.detach().clone() for n, p in self.model.named_parameters()}
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm = float(torch.nn.utils.clip_grad_norm_(self.model.parameters(), .5, error_if_nonfinite=True))
        self.optimizer.step()
        self.scheduler.step()
        deltas = {n: float(((p.detach() - before[n]) ** 2).sum()) for n, p in self.model.named_parameters()}
        changed = sum(int(torch.count_nonzero(p.detach() != before[n])) for n, p in self.model.named_parameters())
        if not changed or not norm or not any(v for n, v in deltas.items() if n.startswith("route_head")) or not any(v for n, v in deltas.items() if n.startswith("forecast_head")):
            raise ContractError("coordinator model/heads did not actually update")
        self.updates += 1
        return {"optimizer_step": self.updates, "loss": float(loss.detach()), "route_loss": float(route_loss.detach()),
                "synthetic_forecast_loss": float(forecast_loss.detach()), "gradient_norm_before_clip": norm,
                "changed_parameter_elements": changed, "parameter_delta_l2": math.sqrt(sum(deltas.values())),
                "before_sha256": before_hash, "after_sha256": parameter_digest(self.model),
                "supervision_source": examples["source"], "calibration": "pending"}

    def advice(self, context):
        self.model.eval()
        with torch.no_grad():
            logits, forecast = self.model(torch.tensor([context_tensor(context)]))
        return {"route": ROUTES[int(logits[0].argmax())], "probability": float(forecast[0]),
                "model_sha256": parameter_digest(self.model), "calibration": "pending", "mode": "advisory_only"}

    def state(self):
        return {"config": asdict(self.config), "feature_version": FEATURE_VERSION,
                "model": self.model.state_dict(), "optimizer": self.optimizer.state_dict(), "scheduler": self.scheduler.state_dict(),
                "batch_rng": self.batch_rng.get_state(), "updates": self.updates, "model_sha256": parameter_digest(self.model)}

    @classmethod
    def restore(cls, state):
        fields(state, {"config", "feature_version", "model", "optimizer", "scheduler", "batch_rng", "updates", "model_sha256"})
        if state["feature_version"] != FEATURE_VERSION:
            raise ContractError("coordinator feature version differs")
        trainer = cls(CoordinatorModelConfig(**state["config"]))
        trainer.model.load_state_dict(state["model"], strict=True)
        trainer.optimizer.load_state_dict(state["optimizer"])
        trainer.scheduler.load_state_dict(state["scheduler"])
        trainer.batch_rng.set_state(state["batch_rng"])
        integer(state["updates"], "restored coordinator updates", 0, trainer.config.steps)
        trainer.updates = state["updates"]
        if parameter_digest(trainer.model) != state["model_sha256"]:
            raise ContractError("coordinator checkpoint checksum differs")
        return trainer
