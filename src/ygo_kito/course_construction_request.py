"""Formal construction wording and coordinator task-language interpretation."""

import re
import unicodedata

from .build_intent import classify_build_intent
from .validation import ContractError, fields


_PERIOD_CODES = {"2022-07": "2207", "2022-10": "2210", "2026-10": "2610"}
_MONTH_NAMES = {"07": r"jul(?:y)?", "10": r"oct(?:ober)?"}
_PERIOD_PATTERNS = {
    period: re.compile(
        rf"(?<![0-9])(?:{code}|(?:20)?{period[2:4]}(?:\s*[-./]\s*{int(period[-2:]):02d}"
        rf"|\s*[-./]\s*{int(period[-2:])}|\s*年\s*0?{int(period[-2:])}\s*月))(?![0-9])"
        rf"|\b{_MONTH_NAMES[period[-2:]]}\.?\s+(?:20)?{period[2:4]}\b"
        rf"|\b{period[:4]}\s+{_MONTH_NAMES[period[-2:]]}\b")
    for period, code in _PERIOD_CODES.items()
}
_COMPETITIVE = (
    r"竞技(?:实力|强度|水平|向)?|竞争力|上位|(?:打|参加|拿去)比赛|比赛(?:强度|能打|能用)|参赛|实战强度"
    r"|\b(?:competitive|tournament(?:[- ](?:ready|viable|play))?)\b"
    r"|競技(?:性|力|向け|用)?|大会(?:で(?:使える|戦える)?|に出られる|用|向け)|実戦(?:向け|用)"
)
_COMPETITIVE_GOAL = re.compile(_COMPETITIVE)
_COMPETITIVE_DECK = re.compile(
    rf"(?:有(?:足够的)?|具备(?:足够的)?|能|可以|可|适合|(?:strong|solid)\s+)?(?:{_COMPETITIVE})(?:用|のある)?"
)
_NEGATED_GOAL = re.compile(
    rf"(?:不要求|不追求|不在意|不需要|不用|无需|不考虑|不想|别)[^,，.。!！?？;；\n]{{0,8}}(?:{_COMPETITIVE})"
    r"|\b(?:not|non[- ]|no|don['’]t\s+(?:need|want))\s*(?:a\s+)?(?:competitive|tournament[- ]ready)\b"
    r"|(?:競技(?:力|向け|性)?|大会向け)(?:は|が)?(?:不要|ではない|でなくていい)"
)
_CARD_COUNT = re.compile(r"(?:[0-9]+|[一二三四五六七八九十百两]+)\s*[张枚]|\b[0-9]+\s+(?:cards?|copies)\b")
_NEGATED_BUILD = re.compile(
    r"(?:不要|不用|不必|不想|不需要|无需|别|暂不)\s*(?:先|现在)?\s*(?:给我)?"
    r"(?:构筑|构建|组(?:卡组|牌组|一套|一副)|做(?:卡组|牌组|一套|一副))"
    r"|\b(?:do not|don['’]t|never|no need to)\s+(?:build|make|create|put together)\b"
    r"|(?:構築|作成)(?:しない|するな|しなくて|は不要)|(?:組まないで|組むな|作らないで|作るな)"
)
_OTHER_OPERATION = re.compile(
    r"(?:做|跑|进入|进行|生成|输出|跳过)\s*cb(?:\s*推理)?"
    r"|训练(?:决斗|构筑|统筹)?模型|(?:跑|进行|模拟)(?:一场|几场)?(?:对局|对战)"
    r"|\b(?:run|perform|start|skip)\s+cb\b|\btrain\s+(?:the\s+|a\s+)?(?:duel\s+)?model\b"
    r"|cb(?:推論|推理)?(?:を|も)?(?:して|実行|開始|スキップ)|モデル(?:を)?学習"
)
_FREE_AXIS = re.compile(
    r"不限(?:主题|主轴|系列)|(?:主题|主轴|系列)(?:不限|随你|随意|都可以)"
    r"|(?:自选|自行选择|自主选择)(?:主题|主轴|系列)"
    r"|\b(?:any|no fixed|no specified)\s+(?:archetype|theme)\b"
    r"|\b(?:archetype|theme)(?:\s+is)?\s+up to you\b"
    r"|テーマ(?:は|の)?(?:お任せ|おまかせ|自由|指定なし)|テーマを自由に選"
)
_DECK_WITH_DESCRIPTION = (
    re.compile(r"(?:一套|一副|(?:环境|卡池|禁限卡表)(?:下)?的)\s*([^0-9,，.。!！?？;；、\n]{0,20}?)(?:卡组|牌组)"),
    re.compile(r"\b(?:a|an|one)\s+([^0-9,.;!?\n]{0,55}?)\bdeck\b"),
    re.compile(r"(?:(?:環境(?:下)?|レギュレーション|[0-9]{4}|月)(?:で|の)|^|[、,。])"
               r"\s*([^0-9,、。.!?;\n]{0,24}?)デッキ"),
)
_UNQUALIFIED_DECK = re.compile(r"(?:^|[,，.。!！?？;；\n])\s*(?:卡组|牌组|デッキ)")
_UNSUPPORTED_AXIS = re.compile(r"\b(?:built around|centered on|based on)\b|(?:を軸に|を中心に)")
_NEGATED_TEARLAMENTS = re.compile(r"ティアラメンツ(?:は|を)?(?:使わない|入れない|除く|ではない|以外|抜き)")
TEARLAMENTS_THEME_ID = "setcode-181"


def course_construction_text(period_id):
    if not isinstance(period_id, str) or period_id not in _PERIOD_CODES:
        raise ContractError("unknown formal construction period")
    wording = "珠泪" if period_id in ("2022-07", "2022-10") else ""
    return f"请构筑一套{_PERIOD_CODES[period_id]}环境下的{wording}卡组，我希望这套卡组有足够的竞技实力。"


def validate_construction_request(request, *, expected_period=None):
    row = fields(request, {"text", "period_id", "theme", "objective"})
    _checked_text(row["text"])
    period = row["period_id"]
    if not isinstance(period, str) or period not in _PERIOD_CODES:
        raise ContractError("unknown construction period")
    if expected_period is not None and period != expected_period:
        raise ContractError("construction request period differs from the loaded period")
    if row["theme"] not in ("tearlaments", None) or row["objective"] != "competitive":
        raise ContractError("unsupported structured construction theme or objective")
    return dict(row)


def _checked_text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ContractError("construction request must contain 1..4096 characters")
    return value


def parse_construction_request(text, *, expected_period=None):
    """Interpret the supported period, optional axis, and competitive goal."""
    normalized = unicodedata.normalize("NFKC", _checked_text(text)).casefold()
    periods = [period for period, pattern in _PERIOD_PATTERNS.items() if pattern.search(normalized)]
    if len(periods) != 1:
        raise ContractError("construction request needs one supported period")
    if _NEGATED_BUILD.search(normalized):
        raise ContractError("construction request explicitly declines building a deck")
    if _OTHER_OPERATION.search(normalized):
        raise ContractError("construction request includes another unsupported operation")
    if _NEGATED_GOAL.search(normalized) or not _COMPETITIVE_GOAL.search(normalized):
        raise ContractError("construction request needs an affirmative competitive goal")
    if _CARD_COUNT.search(normalized):
        raise ContractError("card-count requirements are outside this construction request format")

    if _NEGATED_TEARLAMENTS.search(normalized):
        raise ContractError("construction request has an unsupported or conflicting theme")
    scope = classify_build_intent(normalized.replace("ティアラメンツ", "珠泪哀歌"))
    if (scope.narrow_terms not in ((), ("珠泪哀歌",)) or scope.broad_terms or scope.excluded_terms
            or "conflicting_or_alternative_scope" in scope.reasons):
        raise ContractError("construction request has an unsupported or conflicting theme")
    if not scope.narrow_terms:
        descriptions = [value.strip().removesuffix("的").removesuffix("の")
                        for pattern in _DECK_WITH_DESCRIPTION for value in pattern.findall(normalized)]
        if _UNSUPPORTED_AXIS.search(normalized) or any(
                value and not (_COMPETITIVE_DECK.fullmatch(value) or _FREE_AXIS.fullmatch(value))
                for value in descriptions):
            raise ContractError("construction request has an unsupported named theme")
        if not (descriptions or _UNQUALIFIED_DECK.search(normalized) or _FREE_AXIS.search(normalized)):
            raise ContractError("construction request needs a recognized theme or an unrestricted deck")
    return validate_construction_request(
        {"text": text, "period_id": periods[0],
         "theme": "tearlaments" if scope.narrow_terms else None, "objective": "competitive"},
        expected_period=expected_period,
    )
