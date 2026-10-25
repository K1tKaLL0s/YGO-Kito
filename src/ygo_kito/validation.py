"""Small strict JSON boundary shared by the CLI, storage and engine contracts."""

import json
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """Malformed or unsupported structured input."""


def fields(value: Any, required: set[str], optional: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise ContractError("expected an object")
    if required - value.keys():
        raise ContractError("missing fields: " + ", ".join(sorted(required - value.keys())))
    if value.keys() - required - (optional or set()):
        # Do not echo arbitrary field contents into policy or operational logs.
        raise ContractError("unexpected fields")
    return value


def text(value: Any, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ContractError(f"{label} must be a nonempty string")
    return value


def integer(value: Any, label: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ContractError(f"{label} must be an integer within its permitted range")
    return value


def member(value: Any, label: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ContractError(f"unsupported {label}")
    return value


def array(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    return value


def strings(value: Any, label: str) -> tuple[str, ...]:
    result = tuple(text(item, label) for item in array(value, label))
    if len(result) != len(set(result)):
        raise ContractError(f"duplicate {label}")
    return result


def language_map(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ContractError(f"{label} must be a nonempty language-to-text object")
    for language, content in value.items():
        text(language, "language")
        text(content, label)
    return dict(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON fields")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ContractError("non-finite JSON numbers are not supported")


def parse_json(source: str) -> Any:
    return json.loads(
        source,
        object_pairs_hook=_unique_object,
        parse_constant=_invalid_constant,
    )


def read_json(path: Path) -> Any:
    return parse_json(path.read_text(encoding="utf-8"))
