"""Engineering forecast scope and predeclared bounded-score feedback policy."""

from dataclasses import asdict, dataclass
import math

from .agent_registry import identifier
from .contracts import Versions
from .validation import ContractError, array, fields, integer, member, text

SOURCES = ("real_engine", "synthetic_contract_test")
OUTCOMES = ("win", "loss", "draw", "timeout", "crash", "invalid_action")
ROUTES = ("build_goal", "build_optimizer", "register_forecast", "evaluate_duel", "train_duel", "diagnose", "stop")


def probability(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ContractError(label + " must be finite within [0,1]")
    return float(value)


def sha256(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError("expected lowercase SHA-256")
    return value


@dataclass(frozen=True)
class FeedbackPolicy:
    checkpoints: tuple = (25, 50, 75, 100, 125, 250, 500, 750, 1000)
    minimum_matches: int = 25
    margin: float = .1
    family_alpha: float = .05
    draw_score: float = 0.
    calibration: str = "pending"
    schema_version: int = 1

    def __post_init__(self):
        integer(self.schema_version, "feedback schema", 1, 1)
        integer(self.minimum_matches, "minimum matches", 1, 100)
        if not isinstance(self.checkpoints, tuple) or list(self.checkpoints) != sorted(set(self.checkpoints)):
            raise ContractError("feedback checkpoints must be sorted and unique")
        for n in self.checkpoints:
            integer(n, "feedback checkpoint", self.minimum_matches, 1000)
        if (100 not in self.checkpoints or 1000 not in self.checkpoints or
                not any(n < 100 for n in self.checkpoints) or not any(100 < n < 1000 for n in self.checkpoints)):
            raise ContractError("predeclare checks before and between the 100/1000 horizons")
        if not 0 < probability(self.margin, "margin") < 1 or not 0 < probability(self.family_alpha, "family alpha") < 1:
            raise ContractError("margin/alpha must be strictly between zero and one")
        probability(self.draw_score, "draw score")
        if self.calibration != "pending":
            raise ContractError("formal calibration is not established by this engineering policy")

    @classmethod
    def from_dict(cls, value):
        d = dict(fields(value, set(), set(cls.__dataclass_fields__)))
        if "checkpoints" in d:
            d["checkpoints"] = tuple(array(d["checkpoints"], "checkpoints"))
        return cls(**d)

    def to_dict(self):
        return dict(asdict(self), checkpoints=list(self.checkpoints))

    def assess(self, n, score_sum, forecast, ordinal):
        """One-sided Hoeffding + finite looks + summable forecast alpha spending.

        Conditional on fixed forecasts and independent [0,1] games with a stable
        mean, each forecast gets alpha/(k(k+1)), then divides it over its looks.
        Operational calibration/independence is not proven by a unit test.
        """
        integer(n, "observed matches", 1)
        integer(ordinal, "forecast ordinal", 1)
        probability(forecast, "forecast")
        mean = score_sum / n
        probability(mean, "observed mean")
        if n not in self.checkpoints:
            return None
        alpha = self.family_alpha / (ordinal * (ordinal + 1))
        radius = math.sqrt(math.log(len(self.checkpoints) / alpha) / (2 * n))
        upper = min(1., mean + radius)
        return {"matches": n, "score_mean": mean, "upper_bound": upper, "forecast": forecast,
                "margin": self.margin, "low": upper < forecast - self.margin,
                "forecast_alpha": alpha, "per_look_alpha": alpha / len(self.checkpoints),
                "calibration": "pending", "assumption": "independent bounded games with fixed scope/stable mean"}


def evaluation_scope(value, candidate, policy):
    d = fields(value, {"actor_policy_sha256", "duel_lora", "opponents", "initiative_weights", "unit", "prediction_target", "versions"})
    sha256(d["actor_policy_sha256"])
    if d["duel_lora"] is not None:
        text(d["duel_lora"], "duel LoRA version")
    member(d["unit"], "evaluation unit", ("BO1", "BO3"))
    expected = "win_rate" if policy.draw_score == 0 else "expected_match_score"
    if d["prediction_target"] != expected:
        raise ContractError("forecast target differs from declared draw scoring")
    if Versions.from_dict(d["versions"]) != Versions.from_dict(candidate["task"]["environment"]["versions"]):
        raise ContractError("evaluation scope versions differ from candidate")
    opponents = array(d["opponents"], "opponent distribution")
    integer(len(opponents), "opponent count", 1, 32)
    seen = set()
    for opponent in opponents:
        fields(opponent, {"opponent_id", "deck_sha256", "driver_sha256", "weight"})
        identifier(opponent["opponent_id"])
        if opponent["opponent_id"] in seen:
            raise ContractError("duplicate opponent identity")
        seen.add(opponent["opponent_id"])
        sha256(opponent["deck_sha256"])
        sha256(opponent["driver_sha256"])
        if probability(opponent["weight"], "opponent weight") <= 0:
            raise ContractError("opponent weights must be positive")
    if not math.isclose(sum(o["weight"] for o in opponents), 1., abs_tol=1e-9):
        raise ContractError("opponent weights must sum to one")
    weights = array(d["initiative_weights"], "initiative weights")
    if len(weights) != 2 or not math.isclose(sum(probability(w, "initiative weight") for w in weights), 1., abs_tol=1e-9):
        raise ContractError("declare first/second weights summing to one")
    # List order and int/float spelling are not new opponent/initiative scopes.
    return dict(d, opponents=[dict(o, weight=float(o["weight"])) for o in sorted(opponents, key=lambda o: o["opponent_id"])],
                initiative_weights=[float(w) for w in weights])


def rule_route(context):
    fields(context, {"goal_valid", "card_list_valid", "has_forecast", "warning", "rebuild_required",
                     "operation_error", "system_error", "remaining_tasks", "completed_matches", "score_mean", "forecast"})
    for key in ("goal_valid", "card_list_valid", "has_forecast", "warning", "rebuild_required", "operation_error", "system_error"):
        if type(context[key]) is not bool:
            raise ContractError("coordinator flags must be bool")
    integer(context["remaining_tasks"], "remaining task budget", 0, 10000)
    integer(context["completed_matches"], "completed matches", 0)
    for key in ("score_mean", "forecast"):
        if context[key] is not None:
            probability(context[key], key)
    if not context["remaining_tasks"]:
        return "stop", "budget_exhausted; required rebuild stays queued"
    if not context["goal_valid"] or not context["card_list_valid"]:
        return "build_goal", "goal/card-list not verified"
    if context["rebuild_required"]:
        return "build_goal", "mandatory_rebuild; model advice cannot waive it"
    if context["system_error"]:
        return "diagnose", "system failure; keep aggregate failure accounting"
    if context["operation_error"]:
        return "train_duel", "operation error; not automatically a construction defect"
    if context["warning"]:
        return "build_optimizer", "construction reevaluation requested"
    if not context["has_forecast"]:
        return "register_forecast", "register versioned prediction before validation games"
    return "evaluate_duel", "frozen scoped evaluation"
