"""Constraint-checked building candidates and bounded real-core goal validation.

Conditional first-turn normal and explicit extra-deck route intents are supported.
Card-list legality, conditional route success and quality are separate results.
"""

from collections import Counter
from dataclasses import asdict
from functools import cached_property
from pathlib import Path, PurePosixPath
import sqlite3
import time
import math

from .build_contracts import BuildTask, DeckParts, ZONES, digest
from .card_identity import native_card_identity, rule_name_id
from .contracts import ActionSelection, Versions
from .deck_profile import validate_deck_parts
from .native import NativeError, NativeNormalEngine, banlist_limits
from .native_assets import verify_resources
from .normal_duel import request_digest
from .validation import ContractError, fields, integer

ROUND_CANDIDATE_LIMIT = 5

EXTRA_TYPES = 0x40 | 0x2000 | 0x800000 | 0x4000000


class MissingNativeScript(NativeError):
    def __init__(self, files):
        self.files = tuple(files)
        super().__init__("missing locked Lua source: " + ", ".join(self.files))


class CatalogNativeEngine(NativeNormalEngine):
    """Use the rule-name field of the locked client/core card-data contract."""

    def __init__(self, assets, **options):
        self._catalog_assets = assets
        self._failed_scripts = set()
        super().__init__(assets.root, **options)

    def _deck_limits(self):
        # The base reader also keeps rows without display text for generated
        # entities. The joined catalog supplies the printed-identity evidence.
        self._rows.update(self._catalog_assets.rows)
        return dict(self._catalog_assets.limits)

    def _install_callbacks(self):
        super()._install_callbacks()
        overrides = self._catalog_assets.native_code_overrides
        original_script, original_card, log_handler = self._callbacks

        def read_script(name, length):
            result = original_script(name, length)
            if not result and name:
                try:
                    relative = name.decode().removeprefix("./").removeprefix("script/")
                except UnicodeDecodeError:
                    return result
                path = PurePosixPath(relative)
                if (path.suffix == ".lua" and not path.is_absolute() and ".." not in path.parts
                        and "\\" not in relative and path.as_posix() == relative):
                    self._failed_scripts.add(relative)
            return result

        def read_card(code, target):
            result = original_card(code, target)
            if identity := overrides.get(code):
                printed, rule_name = identity
                target.contents.alias = printed if printed != code else 0
                target.contents.rule_code = rule_name if rule_name != printed else 0
            return result

        script_reader = self._script_type(read_script)
        card_reader = self._card_type(read_card) if overrides else original_card
        self._callbacks = (script_reader, card_reader, log_handler)
        self.lib.set_script_reader(script_reader)
        if overrides:
            self.lib.set_card_reader(card_reader)

    def _check_callbacks(self):
        try:
            super()._check_callbacks()
        except NativeError as error:
            if self._failed_scripts and (lua := self._catalog_assets.effect_lua_source) is not None:
                missing = sorted(filename for filename in self._failed_scripts if not lua.has_script(filename))
                if missing:
                    raise MissingNativeScript(missing) from error
            raise


class BuildAssets:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.receipt = verify_resources(self.root)
        self._lua_assets_verified = True
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

    @property
    def effect_lua_source(self):
        if not getattr(self, "_lua_assets_verified", False):
            return None
        source = self._locked_lua_source
        source.assert_binding(self.root, self.receipt)
        return source

    @cached_property
    def _locked_lua_source(self):
        from .effect_lua import LuaEffectSource

        return LuaEffectSource(self.root, self.receipt)

    @cached_property
    def native_code_overrides(self):
        return {code: identity for code, row in self.rows.items() if (alias := row.get("alias"))
                and (identity := native_card_identity(self.rows, code)) != (alias, alias)}

    def engine_factory(self, root, **options):
        if Path(root).resolve() != self.root:
            raise ContractError("construction engine cannot use another physical resource root")
        return CatalogNativeEngine(self, **options)

    def environment_for(self, kind):
        from .build_contracts import DISCOVERY_GOALS
        environment = dict(self.environment, versions=dict(self.environment["versions"]))
        if kind in DISCOVERY_GOALS:
            environment["versions"]["card_pool"] = "native-extra-material-v2"
        elif kind=="deck_constraints":
            environment["versions"]["card_pool"]="native-private-knowledge-v5"
        return environment

    def check_task(self, task):
        if not isinstance(task, BuildTask) or task.environment != self.environment_for(task.goal["kind"]):
            raise ContractError("building environment versions differ from locked runtime")
        if any(code not in self.rows or not self.rows[code]["ot"] & 1 or self.rows[code]["type"] & 0x4000 for code in task.pool):
            raise ContractError("building pool contains unknown, non-OCG or token cards")
        required = Counter()
        for req in task.requirements:
            code = req["card_id"]
            required[rule_name_id(self.rows, code)] += req["minimum"]
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
        if task.goal['kind']=='deck_constraints':
            from .build_semantics import validate_counts
            validate_counts(task,deck,self)
        return {"card_list_legal": True, "hard_constraints_preserved": True, "task_sha256": task.sha256,
                "deck_sha256": digest(deck.to_dict()), "historical_rules_verified": False}

    def accepts(self, task, deck):
        try:
            self.validate(task, deck)
            return True
        except ContractError:
            return False

    def validate_skeleton(self, task, deck):
        """Check a partial inventory without inventing its unfilled cards."""
        if not isinstance(deck, DeckParts):
            raise ContractError("typed skeleton inventory required")
        self.check_task(task)
        counts = Counter()
        for zone in ZONES:
            if len(getattr(deck, zone)) > task.sizes[zone]:
                raise ContractError("skeleton exceeds requested section size")
            for code in getattr(deck, zone):
                row = self.rows.get(code)
                if code not in task.pool or not row or not row['ot'] & 1 or row['type'] & 0x4000:
                    raise ContractError("skeleton card outside original environment")
                if zone != 'side' and bool(row['type'] & EXTRA_TYPES) != (zone == 'extra'):
                    raise ContractError("skeleton card in wrong section")
                counts[rule_name_id(self.rows, code)] += 1
        if any(n > self.limits.get(code, 3) for code, n in counts.items()):
            raise ContractError("skeleton exceeds combined copy limits")
        for req in task.requirements:
            if not req['minimum'] <= getattr(deck, req['zone']).count(req['card_id']) <= req['maximum']:
                raise ContractError("skeleton changed fixed card requirements")
        if task.goal['kind'] == 'deck_constraints':
            from .build_semantics import count
            if any(count(deck, r, self.rows) > r['maximum'] for r in task.goal['constraints']):
                raise ContractError("skeleton exceeds original semantic maximum")
        return {'task_sha256': task.sha256, 'deck_sha256': digest(deck.to_dict()),
                'unfilled': {z: task.sizes[z] - len(getattr(deck, z)) for z in ZONES}}

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


class DeckEdits:
    """Check small edits against one legal inventory before building a listing."""

    def __init__(self, task, assets, base):
        from .build_semantics import count

        self.task = task
        self.assets = assets
        self.counts = {zone: Counter(getattr(base, zone)) for zone in ZONES}
        self.pool = set(task.pool)
        self.aliases = Counter()
        for counts in self.counts.values():
            for card, quantity in counts.items():
                self.aliases[rule_name_id(assets.rows, card)] += quantity
        self.constraints = [
            (item, count(base, item, assets.rows))
            for item in task.goal.get("constraints", ())
        ]

    def rejection(self, changes):
        from .build_semantics import matches

        aliases = Counter()
        deltas = {}
        for zone in ZONES:
            edit = changes[zone]
            removed, added = Counter(edit["removed"]), Counter(edit["added"])
            if len(edit["removed"]) != len(edit["added"]):
                return "deck does not preserve required section sizes"
            if removed - self.counts[zone]:
                return "removed card is absent from the original section"
            for card in added:
                if card not in self.pool:
                    return "card absent from declared OCG pool"
                if zone != "side" and bool(self.assets.rows[card]["type"] & EXTRA_TYPES) != (zone == "extra"):
                    return "card is in the wrong section"
            delta = deltas[zone] = added.copy()
            delta.subtract(removed)
            for card, quantity in delta.items():
                aliases[rule_name_id(self.assets.rows, card)] += quantity
        if any(self.aliases[card] + quantity > self.assets.limits.get(card, 3)
               for card, quantity in aliases.items()):
            return "combined main/extra/side alias limit exceeded"
        for requirement in self.task.requirements:
            zone, card = requirement["zone"], requirement["card_id"]
            quantity = self.counts[zone][card] + deltas[zone][card]
            if not requirement["minimum"] <= quantity <= requirement["maximum"]:
                return "deck violates a fixed goal/card constraint"
        for item, before in self.constraints:
            after = before + sum(quantity for zone in item["zones"] for card, quantity in deltas[zone].items()
                                 if quantity and matches(self.assets.rows[card], item["predicate"]))
            if not item["minimum"] <= after <= item["maximum"]:
                return "deck violates semantic count constraint: " + item["id"]
        return None

    def inventory(self, changes):
        return {zone: self.counts[zone] - Counter(changes[zone]["removed"]) + Counter(changes[zone]["added"])
                for zone in ZONES}

    def materialize(self, changes):
        inventory = self.inventory(changes)
        return DeckParts(*(tuple(sorted(inventory[zone].elements())) for zone in ZONES))


def candidate_limit(task):
    return min(ROUND_CANDIDATE_LIMIT, task.candidate_budget)


def _goal_candidates(task, assets, base=None, *, skeleton=None, candidate_ids=None, draft_graph=None, catalog=None):
    """Bounded constraint construction followed by model ranking, not learned rule code."""
    assets.check_task(task)
    if task.goal['kind']=='deck_constraints':
        from .build_semantics import solve_candidates
        return solve_candidates(task,assets,base,skeleton=skeleton,candidate_ids=candidate_ids,
                                candidate_count=candidate_limit(task), draft_graph=draft_graph, catalog=catalog)['candidates']
    if skeleton is not None:
        assets.validate_skeleton(task, skeleton)
    if base is not None:
        if not isinstance(base, DeckParts):
            raise ContractError("typed existing deck required")
        # A legal existing deck may miss the new goal; illegal listings are rejected.
        validate_deck_parts(base.to_dict(), assets.rows, assets.limits, allowed=set(task.pool))
    found = []
    if base is not None and assets.accepts(task, base):
        found.append(base)
    for rotation in range(min(4, candidate_limit(task) - len(found))):
        parts = {zone: [] for zone in ZONES}
        for req in task.requirements:
            parts[req["zone"]].extend([req["card_id"]] * req["minimum"])
        if skeleton is not None:
            parts = {z: list((Counter(parts[z]) | Counter(getattr(skeleton, z))).elements()) for z in ZONES}
        all_counts = Counter(rule_name_id(assets.rows, c) for cards in parts.values() for c in cards)
        valid = True
        allowed = task.pool if candidate_ids is None else tuple(candidate_ids)
        if not set(allowed) <= set(task.pool):
            raise ContractError('candidate query exceeds original task card pool')
        pool = list(allowed[rotation:] + allowed[:rotation])
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
                    alias = rule_name_id(assets.rows, code)
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
        if valid:
            candidate = _parts(parts)
            if assets.accepts(task, candidate) and candidate not in found:
                found.append(candidate)
    return found


def goal_candidates(task, assets, base=None, *, skeleton=None, feedback=(), return_portfolio=False,
                    mechanism_groups=None, trace=None, graph=None, candidate_ids=None, rank_ideas=None,
                    recognized_cards=(), draft_graph=None, catalog=None):
    from .construction_candidates import portfolio

    if base is not None and assets.accepts(task, base):
        return edit_candidates(task, assets, base, feedback=feedback, return_portfolio=return_portfolio,
                               mechanism_groups=mechanism_groups, trace=trace, graph=graph,
                               candidate_ids=candidate_ids, rank_ideas=rank_ideas,
                               recognized_cards=recognized_cards)
    # Without a complete starting list, fill the requested skeleton first.
    # Each solver call owns a slot; edits of these lists belong to later rounds.
    initial = _goal_candidates(task, assets, base, skeleton=skeleton, candidate_ids=candidate_ids,
                               draft_graph=draft_graph, catalog=catalog)
    rows = portfolio(task, assets, initial=initial, trace=trace)
    if trace is not None:
        trace.update(generator="goal_solver", complete_list_attempt_limit=candidate_limit(task))
    return rows if return_portfolio else [row["deck"] for row in rows]


def edit_candidates(task, assets, base, *, require_edit=False, feedback=(), return_portfolio=False,
                    mechanism_groups=None, trace=None, graph=None, search_offset=0, candidate_ids=None, rank_ideas=None, recognized_cards=(),
                    review_slots=()):
    from .construction_candidates import portfolio

    assets.validate(task, base)
    pool = task.pool if candidate_ids is None else tuple(candidate_ids)
    if not set(pool) <= set(task.pool):
        raise ContractError("edit query exceeds original task card pool")
    edits = DeckEdits(task, assets, base)
    families, zone_limits = {}, {}

    def ideas(zone, other=None):
        removed_cards = sorted(edits.counts[zone])
        added_cards = list(pool) if other is None else sorted(edits.counts[other])
        start = search_offset % max(1, len(removed_cards))
        pool_start = search_offset % max(1, len(added_cards))
        for removed in removed_cards[start:] + removed_cards[:start]:
            for added in added_cards[pool_start:] + added_cards[:pool_start]:
                if added == removed:
                    continue
                change = {z: {"added": [], "removed": []} for z in ZONES}
                change[zone] = {"removed": [removed], "added": [added]}
                generation = {"kind": "single_zone_substitution", "zones": [zone],
                              "removed": {zone: removed}, "added": {zone: added}}
                if other is not None:
                    change[other] = {"removed": [added], "added": [removed]}
                    generation.update(kind="atomic_cross_zone_exchange", zones=[zone, other],
                                      removed={zone: removed, other: added}, added={zone: added, other: removed},
                                      combined_inventory_preserved=True)
                yield change, generation

    # Keep a small menu of edits per section, alternating substitutions and
    # exchanges. These records contain only the cards that would change.
    found = []
    if review_slots:
        # Recall against the whole period. Prefer candidates retrieved by S2,
        # and try another eligible card when retrieval missed this section.
        ranked_pool = tuple(dict.fromkeys((*pool, *task.pool)))
        for slot in review_slots:
            zone, outgoing = slot['zone'], slot['card']
            if not edits.counts[zone].get(outgoing):
                continue
            for incoming in ranked_pool:
                if incoming == outgoing or bool(assets.rows[incoming]['type'] & EXTRA_TYPES) != (zone == 'extra'):
                    continue
                change = {z: dict(removed=[], added=[]) for z in ZONES}
                change[zone] = dict(removed=[outgoing], added=[incoming])
                if not edits.rejection(change):
                    found.append(dict(changes=change, strategy='quality_slot', edited_zones=[zone],
                        proposal_basis=slot['reason'], generation=dict(kind='quality_slot', zone=zone,
                            removed=outgoing, added=incoming, reason=slot['reason'])))
                    break
            if len(found) >= candidate_limit(task) - 1:
                break
    for position, zone in enumerate(ZONES):
        streams = [("single:" + zone, ideas(zone))]
        streams.extend(("transfer:" + zone + "+" + other, ideas(zone, other)) for other in ZONES[position + 1:])
        count = 0
        while streams and count < 32:
            for name, stream in streams[:]:
                stats = families.setdefault(name, {"attempted": 0, "accepted": 0, "filtered": {}, "rejection_samples": []})
                choice = next(stream, None)
                if choice is None:
                    streams.remove((name, stream))
                    continue
                change, generation = choice
                stats["attempted"] += 1
                reason = edits.rejection(change)
                if reason:
                    stats["filtered"][reason] = stats["filtered"].get(reason, 0) + 1
                    if len(stats["rejection_samples"]) < 2:
                        stats["rejection_samples"].append({"edit": generation, "reason": reason})
                    continue
                found.append({"changes": change, "strategy": name, "generation": generation,
                              "edited_zones": generation["zones"], "proposal_basis": generation["kind"]})
                stats["accepted"] += 1
                count += 1
                if count == 32:
                    break
        zone_limits[zone] = {"accepted": count, "limit": 32, "enumeration_complete": not streams}
    rows = portfolio(task, assets, base=base, singles=found, feedback=feedback, require_edit=require_edit,
                     mechanism_groups=mechanism_groups, trace=trace, graph=graph, candidate_ids=candidate_ids,
                     edits=edits, search_offset=search_offset, rank_ideas=rank_ideas, recognized_cards=recognized_cards)
    if trace is not None:
        trace.update(generator="bounded_substitutions_and_atomic_exchanges", families=families,
                     zone_limits=zone_limits, legal_edit_ideas=len(found), portfolio_candidates=len(rows),
                     constraints_checked=["section_sizes", "destination_zone", "combined_alias_copy_limits",
                                          "explicit_task_constraints"])
    return rows if return_portfolio else [row["deck"] for row in rows]


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
    if task.goal['kind']=='deck_constraints':
        if 'route_goal' in task.goal:
            from .build_semantics import verify_combined
            return verify_combined(task,deck,assets,seconds=seconds,attempts=attempts,decision_budget=decision_budget)
        from .build_semantics import proof
        return proof(task,deck,assets)
    if task.goal["kind"] != "normal_summon":
        if task.schema_version == 3 and "route" not in task.goal:
            from .route_search import discover_goal
            return discover_goal(task, deck, assets, seconds=seconds, attempts=attempts, decision_budget=decision_budget)
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
        if hasattr(assets,"adapt_goal_profile"):profile=assets.adapt_goal_profile(profile)
        factory=getattr(assets,"engine_factory",NativeNormalEngine)
        with factory(assets.root, scenario="effect-duel", deck_profile=profile, seed=seed) as engine:
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
