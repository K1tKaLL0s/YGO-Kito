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
        "reason": "full-duel backend unavailable; native-smoke separately supports one real normal summon",
        "native_smoke": {"implemented": True, "requires_prepared_resources": True, "full_duel_supported": False},
    }


def open_engine() -> RuleEngine:
    raise EngineUnavailable("full-duel YGOPro/萌卡 backend is not integrated; native-smoke is limited to one real summon")
