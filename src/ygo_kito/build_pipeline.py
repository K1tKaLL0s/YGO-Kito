"""Constraint-checked building candidates and bounded real-core goal validation.

Conditional first-turn normal and explicit extra-deck route intents are supported.
Card-list legality, conditional route success and quality are separate results.
"""

from collections import Counter
from dataclasses import asdict
from pathlib import Path
import sqlite3
import time
import math

from .build_contracts import BuildTask, DeckParts, ZONES, digest
from .contracts import ActionSelection, Versions
from .deck_profile import validate_deck_parts
from .native import NativeError, NativeNormalEngine, banlist_limits
from .native_assets import verify_resources
from .normal_duel import request_digest
from .validation import ContractError, fields, integer

EXTRA_TYPES = 0x40 | 0x2000 | 0x800000 | 0x4000000


class BuildAssets:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.receipt = verify_resources(self.root)
        src = self.root / "engine-src"
        with sqlite3.connect((src / "database/locales/zh-CN/cards.cdb").as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            self.rows = {r["id"]: dict(r) for r in db.execute("SELECT d.*,t.name,t.desc FROM datas d JOIN texts t ON d.id=t.id")}
        self.limits = banlist_limits(src / "client/lflist.conf")
        h = self.receipt["resources"]
        versions = Versions(self.receipt["source_commits"]["core"], h["scripts"], h["cards"],
                            h["client_protocol"], "native-effect-duel-v1", "2026.10:" + h["banlist"])
        self.environment = {"environment_id": "custom-native-current", "versions": asdict(versions),
                            "authority": "custom", "release_cutoff": None}

    def environment_for(self, kind):
        environment = dict(self.environment, versions=dict(self.environment["versions"]))
        if kind in ("synchro_summon", "xyz_summon"):
            environment["versions"]["card_pool"] = "native-extra-material-v2"
        return environment

    def check_task(self, task):
        if not isinstance(task, BuildTask) or task.environment != self.environment_for(task.goal["kind"]):
            raise ContractError("building environment versions differ from locked runtime")
        if any(code not in self.rows or not self.rows[code]["ot"] & 1 or self.rows[code]["type"] & 0x4000 for code in task.pool):
            raise ContractError("building pool contains unknown, non-OCG or token cards")
        required = Counter()
        for req in task.requirements:
            code = req["card_id"]
            required[self.rows[code]["alias"] or code] += req["minimum"]
        if any(n > self.limits.get(code, 3) for code, n in required.items()):
            raise ContractError("required cards conflict with combined alias/banlist limits")

    def validate(self, task, deck):
        if not isinstance(task, BuildTask) or not isinstance(deck, DeckParts):
            raise ContractError("typed building task and deck required")
        self.check_task(task)
        validate_deck_parts(deck.to_dict(), self.rows, self.limits, allowed=set(task.pool))
        for zone in ZONES:
            if len(getattr(deck, zone)) != task.sizes[zone]:
                raise ContractError("deck does not preserve required section sizes")
        for req in task.requirements:
            count = getattr(deck, req["zone"]).count(req["card_id"])
            if not req["minimum"] <= count <= req["maximum"]:
                raise ContractError("deck violates a fixed goal/card constraint")
        return {"card_list_legal": True, "hard_constraints_preserved": True, "task_sha256": task.sha256,
                "deck_sha256": digest(deck.to_dict()), "historical_rules_verified": False}

    def accepts(self, task, deck):
        try:
            self.validate(task, deck)
            return True
        except ContractError:
            return False

    def facts(self, code):
        row = self.rows[code]
        return [row["atk"] / 10000, row["def"] / 10000, (row["level"] & 0xff) / 12,
                float(bool(row["type"] & 1)), float(bool(row["type"] & 0x10)), float(bool(row["type"] & EXTRA_TYPES))]

    def effect_receipts(self, task):
        # Read real public effects/attributes; this does not pretend to parse all effects.
        return [{"card_id": code, "name": self.rows[code]["name"],
                 "effect_text_sha256": digest(self.rows[code]["desc"]),
                 "source_cards_sha256": self.receipt["resources"]["cards"]} for code in task.pool]


def _parts(parts):
    return DeckParts(*(tuple(sorted(parts[zone])) for zone in ZONES))


def goal_candidates(task, assets, base=None):
    """Bounded constraint construction followed by model ranking, not learned rule code."""
    assets.check_task(task)
    if base is not None:
        if not isinstance(base, DeckParts):
            raise ContractError("typed existing deck required")
        # A legal existing deck may miss the new goal; illegal listings are rejected.
        validate_deck_parts(base.to_dict(), assets.rows, assets.limits, allowed=set(task.pool))
    found = []
    if base is not None and assets.accepts(task, base):
        found.append(base)
    for rotation in range(min(4, task.candidate_budget)):
        parts = {zone: [] for zone in ZONES}
        for req in task.requirements:
            parts[req["zone"]].extend([req["card_id"]] * req["minimum"])
        all_counts = Counter(assets.rows[c]["alias"] or c for cards in parts.values() for c in cards)
        valid = True
        pool = list(task.pool[rotation:] + task.pool[:rotation])
        for zone in ZONES:
            priority = ([] if base is None else list(getattr(base, zone))) + pool
            while len(parts[zone]) < task.sizes[zone]:
                progressed = False
                for code in priority:
                    row = assets.rows.get(code)
                    if not row or not row["ot"] & 1 or row["type"] & 0x4000:
                        continue
                    if zone in ("main", "extra") and bool(row["type"] & EXTRA_TYPES) != (zone == "extra"):
                        continue
                    alias = row["alias"] or code
                    maximum = next((r["maximum"] for r in task.requirements if r["zone"] == zone and r["card_id"] == code), 3)
                    if all_counts[alias] >= assets.limits.get(alias, 3) or parts[zone].count(code) >= maximum:
                        continue
                    parts[zone].append(code)
                    all_counts[alias] += 1
                    progressed = True
                    if len(parts[zone]) == task.sizes[zone]:
                        break
                if not progressed:
                    valid = False
                    break
        candidate = _parts(parts)
        if valid and assets.accepts(task, candidate) and candidate not in found:
            found.append(candidate)
        if len(found) >= task.candidate_budget:
            break
    return found


def edit_candidates(task, assets, base, *, require_edit=False):
    assets.validate(task, base)
    found = [] if require_edit else [base]
    for zone in ZONES:
        for removed in sorted(set(getattr(base, zone))):
            for added in task.pool:
                if added == removed:
                    continue
                parts = base.to_dict()
                parts[zone].remove(removed)
                parts[zone].append(added)
                candidate = _parts(parts)
                if assets.accepts(task, candidate) and candidate not in found:
                    found.append(candidate)
                if len(found) >= task.candidate_budget:
                    return found
    return found


def deck_changes(before, after):
    changes = []
    for zone in ZONES:
        old, new = Counter(getattr(before, zone)), Counter(getattr(after, zone))
        for code in sorted(old.keys() | new.keys()):
            if old[code] != new[code]:
                changes.append({"zone": zone, "card_id": code, "before": old[code], "after": new[code]})
    return changes


def apply_changes(before, changes):
    parts, seen = before.to_dict(), set()
    for change in changes:
        fields(change, {"zone", "card_id", "before", "after"})
        zone, code = change["zone"], change["card_id"]
        if zone not in ZONES or (zone, code) in seen:
            raise ContractError("duplicate/unknown deck change")
        seen.add((zone, code))
        integer(code, "edited card ID", 1, 2**32 - 1)
        integer(change["before"], "old card count", 0, 3)
        integer(change["after"], "new card count", 0, 3)
        if parts[zone].count(code) != change["before"]:
            raise ContractError("deck change does not match prior version")
        parts[zone] = [c for c in parts[zone] if c != code] + [code] * change["after"]
    return _parts(parts)


def engineering_proxy(deck, assets):
    """Explicit weak label: mean printed monster ATK, never stability or win rate."""
    return sum(max(assets.rows[c]["atk"], 0) for c in deck.main if assets.rows[c]["type"] & 1) / len(deck.main)


def verify_goal(task, deck, assets, *, seconds=10., attempts=16, decision_budget=100):
    integer(attempts, "route attempts", 0, 64 if isinstance(task, BuildTask) and task.goal["kind"] != "normal_summon" else 16)
    integer(decision_budget, "route decision budget", 1, 100)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 30:
        raise ContractError("route time budget outside CPU proof range")
    assets.validate(task, deck)
    if task.goal["kind"] != "normal_summon":
        from .extra_routes import verify_extra_goal
        return verify_extra_goal(task, deck, assets, seconds=seconds, attempts=attempts, decision_budget=decision_budget)
    row = assets.rows[task.goal["card_id"]]
    if deck.extra or row["type"] != 17 or (row["level"] & 0xff) > 4:
        return {"status": "unsupported_route", "card_list_legal": True,
                "unmet": ["extra-deck or non-low-level-normal goal not supported"], "core_attempts": []}
    started, trials = time.monotonic(), []
    for seed in (7, 24, 1724, *range(13))[:attempts]:
        if time.monotonic() - started >= seconds:
            break
        audit = []
        profile = {"schema_version": 1, "name": "conditional-build-goal-proof", "decks": [list(deck.main), list(deck.main)]}
        with NativeNormalEngine(assets.root, scenario="effect-duel", deck_profile=profile, seed=seed) as engine:
            request = engine.next_decision()
            opening = engine._observation(0)  # Legitimate own hand; never supplied to build-model features.
            present = any(c.zone == "hand" and c.card_id == task.goal["card_id"] for c in opening.cards)
            trials.append({"seed_audit_only": seed, "declared_opening_condition_met": present})
            if not present:
                continue
            for _ in range(decision_budget):
                if request is None or engine.turn > 1 or time.monotonic() - started >= seconds:
                    break
                cards = {c.ref: c for c in request.observation.cards}
                action = next((a for a in request.actions if request.observation.observer == 0 and a.kind == "summon" and
                               any(cards[r].card_id == task.goal["card_id"] for r in a.card_refs)), None)
                if action is None:
                    action = next((a for a in request.actions if a.kind == "pass"), request.actions[0])
                audit.append({"player": request.observation.observer, "request_sha256": request_digest(request),
                              "action_id": action.action_id})
                engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
                request = engine.next_decision()
                public = engine._observation(0)
                if (61 in [e["kind"] for e in engine.events] and
                        any(c.zone == "monster" and c.controller == 0 and c.card_id == task.goal["card_id"] for c in public.cards)):
                    return {"status": "verified_success", "card_list_legal": True,
                            "task_sha256": task.sha256, "deck_sha256": digest(deck.to_dict()),
                            "starting_condition": task.goal["starting_conditions"], "random_dependency": "goal card must be in the actual opening hand",
                            "core_attempts": trials, "responses": audit, "core_event_kinds": [e["kind"] for e in engine.events],
                            "trajectory_sha256": digest(audit), "elapsed_seconds": time.monotonic() - started, "unmet": []}
    return {"status": "not_found_within_budget", "card_list_legal": True, "core_attempts": trials,
            "unmet": ["conditional route not verified within declared search budget; not proof of impossibility"]}


def alternate_build(task, assets, models, encoder, *, base=None, stages=4, seconds=30., lora_versions=None):
    import torch
    from .duel_model import parameter_digest
    if lora_versions is not None:
        from .coord_contracts import sha256
        fields(lora_versions, {"build_goal", "build_optimizer"})
        for version in lora_versions.values():
            sha256(version)
    integer(stages, "alternating stages", 1, 4)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 60:
        raise ContractError("alternation time budget outside CPU range")
    fixed = task.sha256
    started = time.monotonic()
    current, history, verified, failures = base, [], [], []
    for i in range(stages):
        role = "build_goal" if i % 2 == 0 else "build_optimizer"
        if time.monotonic() - started >= seconds:
            failures.append({"stage": i, "role": role, "status": "budget_exhausted"})
            break
        candidates = goal_candidates(task, assets, current) if role == "build_goal" else edit_candidates(task, assets, current, require_edit=True)
        if not candidates:
            failures.append({"stage": i, "role": role, "status": "no_candidate_within_budget"})
            break
        models[role].eval()
        with torch.no_grad():
            scores = models[role](encoder.batch(task, candidates))
        if not torch.isfinite(scores).all():
            raise ContractError("non-finite building scores")
        selected, proof = None, None
        for index in scores.argsort(descending=True).tolist():
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                failures.append({"stage": i, "role": role, "status": "budget_exhausted"})
                break
            candidate = candidates[index]
            try:
                proof = verify_goal(task, candidate, assets, seconds=min(10., remaining))
            except NativeError as error:
                failures.append({"stage": i, "role": role, "status": "native_route_unverified", "reason": str(error)})
                continue
            if proof["status"] == "verified_success":
                selected = candidate
                break
            failures.append({"stage": i, "role": role, "status": proof["status"], "unmet": proof["unmet"]})
        if selected is None:
            break
        before = current or DeckParts(())
        changes = deck_changes(before, selected)
        if apply_changes(before, changes) != selected or task.sha256 != fixed:
            raise ContractError("alternation failed goal identity/change verification")
        history.append({"stage": i, "role": role, "task_sha256": fixed, "deck": selected.to_dict(),
                        "changes": changes, "model_score_uncalibrated": float(scores[index]), "candidate_count": len(candidates),
                        "model_sha256": parameter_digest(models[role]), "lora_version": (lora_versions or {}).get(role),
                        "versions": task.environment["versions"], "elapsed_seconds": time.monotonic() - started,
                        "uncertainty": "uncalibrated engineering prototype; construction quality unknown",
                        "engineering_proxy": engineering_proxy(selected, assets), "validation": proof})
        verified.append(selected)
        current = selected
    best = max(verified, key=lambda d: engineering_proxy(d, assets)) if verified else None
    stop_reason = ("stage_budget_reached" if len(history) == stages else
                   "time_budget_exhausted" if time.monotonic() - started >= seconds else "no_verified_candidate_within_budget")
    return {"schema_version": 1, "kind": "goal-optimizer-alternation",
            "status": "verified_candidates" if best else "not_found_within_budget", "task_sha256": fixed,
            "stages": history, "best_deck": None if best is None else best.to_dict(),
            "best_criterion": "engineering_mean_printed_attack_proxy_only", "stop_reason": stop_reason,
            "failures": failures, "time_budget_seconds": seconds, "stage_budget": stages,
            "unmet": ["competitive construction quality not evaluated"] + ([] if len(history) == stages else ["requested stages not all verified"]),
            "competitive_ability_validated": False}
