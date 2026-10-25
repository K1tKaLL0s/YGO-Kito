"""Real-rule adapter boundary. There is deliberately no simulated game backend."""

from typing import Protocol

from .contracts import ActionSelection, DecisionRequest


class EngineUnavailable(RuntimeError):
    pass


class RuleEngine(Protocol):
    """Future native adapter owns response bytes and the active decision window.

    Only player-visible DTOs cross this boundary. submit must recheck the current
    run/duel/decision and candidate ID and reject already consumed requests. Native
    debug state must never appear in an observation or ordinary operational log.
    """

    def next_decision(self) -> DecisionRequest | None: ...

    def submit(self, selection: ActionSelection) -> None: ...

    def close(self) -> None: ...


def engine_status() -> dict:
    return {
        "backend": "unconfigured", "implemented": False, "ready": False,
        "reason": "general backend unconfigured; explicit normal/effect main-deck tools are available separately",
        "native_smoke": {"implemented": True, "requires_prepared_resources": True, "full_duel_supported": False},
        "native_normal_duel": {"implemented": True, "scope": "explicit-normal-monster-pool", "general_effect_duels_supported": False},
        "native_effect_duel": {"implemented": True, "scope": "explicit-effect-main-decks", "general_card_pool_supported": False},
        "external_tools": {"local_json_api_implemented": True, "provider_connected": False, "training_backend_configured": False},
    }


def open_engine() -> RuleEngine:
    raise EngineUnavailable("general YGOPro/萌卡 backend unconfigured; use explicit native tools for supported profiles")
