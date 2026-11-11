"""The user's three formal construction requests and their model inputs."""

from .validation import ContractError


_PERIOD_CODES = {"2022-07": "2207", "2022-10": "2210", "2026-10": "2610"}
TEARLAMENTS_THEME_ID = "setcode-181"


def course_construction_request(period_id):
    if not isinstance(period_id, str) or period_id not in _PERIOD_CODES:
        raise ContractError("unknown formal construction period")
    theme = "tearlaments" if period_id != "2026-10" else None
    wording = "珠泪" if theme else ""
    return {
        "text": f"请构筑一套{_PERIOD_CODES[period_id]}环境下的{wording}卡组，我希望这套卡组有足够的竞技实力。",
        "period_id": period_id,
        "theme": theme,
        "objective": "competitive",
    }
