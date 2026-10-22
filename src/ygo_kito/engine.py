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
        "reason": "core/scripts/cards.cdb/protocol/banlist/card pool are not locked or integrated",
    }


def open_engine() -> RuleEngine:
    raise EngineUnavailable("real YGOPro/萌卡 rule engine is not integrated; no duel was started")
