"""JSON CLI for infrastructure checks, never a simulated duel demonstration."""

import argparse
import json
from pathlib import Path
import platform
import sqlite3
import sys
import tomllib

from . import __version__
from .config import load_config
from .contracts import ActionSelection, DecisionRequest, validate_selection
from .engine import EngineUnavailable, engine_status, open_engine
from .storage import Store
from .validation import ContractError, canonical_json, integer, read_json


def parser():
    result = argparse.ArgumentParser(prog="ygo-kito", description=__doc__)
    result.add_argument("--config", type=Path, help="TOML configuration; place before command")
    sub = result.add_subparsers(dest="command", required=True)
    for command in ("status", "config-check", "db-init", "duel-run"):
        sub.add_parser(command)
    sub.add_parser("cards-import").add_argument("input", type=Path)
    sub.add_parser("card-show").add_argument("card_id", type=int)
    sub.add_parser("request-check").add_argument("input", type=Path)
    action = sub.add_parser("action-check")
    action.add_argument("request", type=Path)
    action.add_argument("selection", type=Path)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        match args.command:
            case "status":
                output = {"version": __version__, "python": platform.python_version(),
                          "sqlite": sqlite3.sqlite_version, "config": config.to_dict(), "engine": engine_status()}
            case "config-check":
                output = {"ok": True, "config": config.to_dict()}
            case "db-init":
                Store.initialize(config.database)
                output = {"ok": True, "database": str(config.database), "schema_version": 1}
            case "cards-import":
                dataset = read_json(args.input)
                with Store(config.database) as store:
                    cards, annotations = store.import_dataset(dataset)
                output = {"ok": True, "processed_cards": cards, "processed_annotations": annotations,
                          "rules_verified": False}
            case "card-show":
                integer(args.card_id, "card_id", 1, 2**63 - 1)
                with Store(config.database) as store:
                    card = store.get_card(args.card_id)
                    if card is None:
                        raise ContractError("card_id not found")
                    output = {"card": card.to_dict(), "annotations": [a.to_dict() for a in store.annotations(args.card_id)]}
            case "request-check" | "action-check":
                request = DecisionRequest.from_dict(read_json(args.input if args.command == "request-check" else args.request))
                output = {"ok": True, "validation": "contract_only", "rules_verified": False,
                          "run_id": request.context.run_id, "duel_id": request.duel_id,
                          "decision_id": request.decision_id, "action_count": len(request.actions)}
                if args.command == "action-check":
                    selection = ActionSelection.from_dict(read_json(args.selection))
                    output["action_id"] = validate_selection(request, selection).action_id
            case "duel-run":
                open_engine()  # Always raises until a real compatible adapter is implemented.
                raise EngineUnavailable("no runnable engine backend")
        print(canonical_json(output))
        return 0
    except EngineUnavailable as error:
        code = "ENGINE_NOT_IMPLEMENTED"
        message = str(error)
    except (ContractError, json.JSONDecodeError, tomllib.TOMLDecodeError, UnicodeError) as error:
        code = "INVALID_INPUT"
        # JSON/TOML parser messages may include input fragments; do not expose them.
        message = str(error) if isinstance(error, ContractError) else "malformed input document"
    except (OSError, sqlite3.Error):
        code = "STORAGE_ERROR"
        message = "file/database unavailable; verify path, permissions and schema"
    print(canonical_json({"ok": False, "error": {"code": code, "message": message}}), file=sys.stderr)
    return 2
