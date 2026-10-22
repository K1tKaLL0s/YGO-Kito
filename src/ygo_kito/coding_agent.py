"""Replaceable external coding handoff. Preparing a packet never invokes a paid model."""

from pathlib import Path
import re
import shutil
import subprocess
from typing import Protocol

from .validation import ContractError, canonical_json, fields, strings, text


class CodingAgentAdapter(Protocol):
    def prepare(self, request: dict) -> dict: ...


class CodeBuddyCLIAdapter:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()

    def prepare(self, request):
        d = fields(request, {"task_id", "checklist_ids", "goal", "model"})
        for key in ("task_id", "goal", "model"):
            text(d[key], key)
        ids = strings(d["checklist_ids"], "checklist IDs")
        if not ids:
            raise ContractError("handoff requires checklist IDs")
        known = set(re.findall(r"\*\*([A-Z][A-Z0-9]*-\d+) ", (self.workspace / "docs/plans/MASTER-CHECKLIST.md").read_text()))
        if set(ids) - known:
            raise ContractError("unknown checklist ID")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", d["model"]):
            raise ContractError("model ID must be explicit and cannot be a command option")
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=self.workspace, text=True).strip()
        if not branch or branch in ("main", "master"):
            raise ContractError("coding handoff requires a work branch")
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.workspace, text=True).strip()
        packet = dict(d, branch=branch, head=head, workspace=str(self.workspace),
            constraints=["preserve learning TODO", "no merge or force push", "no paid training or credential changes",
                         "save and stop at 20 percent quota", "update MASTER-CHECKLIST evidence"],
            provider="codebuddy-cli", cli_available=shutil.which("codebuddy") is not None,
            model_verified=False, external_end_to_end_verified=False, executed=False)
        # Explicit model only: no fallback endpoint, key setup, shell interpolation or invocation.
        prompt = canonical_json({"task_id": d["task_id"], "checklist_ids": list(ids), "goal": d["goal"],
                                 "branch": branch, "constraints": packet["constraints"]})
        packet["suggested_argv"] = ["codebuddy", "-p", "--model", d["model"], prompt]
        return packet
