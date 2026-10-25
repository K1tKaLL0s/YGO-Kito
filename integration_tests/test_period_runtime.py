"""Lawful pinned-core period plumbing with explicit engineering date manifests.

The dates/roster are test inputs, not verified historical facts or user decks.
No fault injection, memory experiment, process termination or provider is used.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_pipeline import BuildAssets, edit_candidates, engineering_proxy, verify_goal
from ygo_kito.contracts import ActionSelection
from ygo_kito.data_isolation import DataIndex
from ygo_kito.deck_intake import PERIODS
from ygo_kito.native import banlist_limits
from ygo_kito.normal_duel import request_digest
from ygo_kito.opponent_pool import replay_private
from ygo_kito.period_runtime import PeriodBuildAssets
from ygo_kito.period_host import load_period_host
from ygo_kito.training_input import _profile, load_training_inputs
from ygo_kito.route_search import discover_goal, replay_discovered_goal
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


def engineering_period_fixture(folder):
    """Real files/core, with deliberately unqualified engineering input dates."""
    base = BuildAssets(CACHE)
    sections = {"2022-07": "2022.7", "2022-10": "2022.10", "2026-10": "2026.10"}
    limits = {p: banlist_limits(CACHE / "engine-src/client/lflist.conf", s) for p, s in sections.items()}
    codes = [c for c, r in sorted(base.rows.items()) if r["type"] == 17 and r["alias"] == 0 and r["ot"] & 1
             and c < 100000000 and 1 <= r["level"] <= 4 and all(limits[p].get(c, 3) >= 1 for p in PERIODS)][:60]
    if len(codes) != 60:
        raise AssertionError("engineering fixture requires sixty real eligible normal cards")
    intake = json.loads((ROOT / "configs/user-deck-intake-template-v1.json").read_text(encoding="utf-8"))
    intake["intake_id"] = "period-engineering-core"
    policy = json.loads((ROOT / "configs/user-training-input-template-v1.json").read_text(encoding="utf-8"))
    policy.update(source="synthetic_contract_test", training_input_id="period-engineering-input")
    for index, slot in enumerate(intake["slots"]):
        offset = index
        slot["deck"] = {"format": "json", "source": "engineering-explicit-allowlist-not-user-deck",
            "content": {"main": codes[offset:offset + 40], "extra": [], "side": []}}
        if index >= 3:
            slot["periods"] = list(PERIODS)
            slot["controller"] = {"controller": "rule_baseline", "provider": None, "model": None,
                                  "driver_version": "visible-effects-first-v1"}
    def artifact(path):
        return {"path": str(path.relative_to(CACHE)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source": "engineering-current-physical-files-and-unverified-date-manifest"}
    assets = {}
    for index, period in enumerate(PERIODS):
        cutoff = period + "-01"
        release = folder / (period + "-engineering-dates.json")
        release.write_text(json.dumps({"schema_version": 1, "period_id": period, "release_cutoff": cutoff,
            "cards": [{"card_id": c, "ocg_release_date": cutoff} for c in codes]}), encoding="utf-8")
        env = {"release_cutoff": cutoff, "banlist_effective": period + "-01", "banlist_section": sections[period],
            "catalog": artifact(CACHE / "engine-src/database/locales/zh-CN/cards.cdb"), "releases": artifact(release),
            "banlist": artifact(CACHE / "engine-src/client/lflist.conf")}
        intake["environments"][period] = env
        assets[period] = PeriodBuildAssets(CACHE, period, env, CACHE, evidence_source="engineering_fixture")
        phase = policy["periods"][period]
        phase["versions"] = deepcopy(assets[period].environment["versions"])
        actor = DeckParts.from_dict(intake["slots"][index]["deck"]["content"])
        for part_index, purpose in enumerate(("train", "validation", "final_eval")):
            ordinals = range(1, 7) if purpose == "train" else [7] if purpose == "validation" else [8]
            opponents = []
            for ordinal in ordinals:
                slot = intake["slots"][ordinal + 2]
                profile = _profile(actor, DeckParts.from_dict(slot["deck"]["content"]), 5)
                opponent = assets[period].bind_rule_opponent(profile, slot["slot_id"])
                opponents.append({"slot_id": slot["slot_id"], "binding": deepcopy(opponent.binding)})
            phase["partitions"][purpose] = {"opponents": opponents, "seeds": [1000 * (index + 1) + part_index * 100 + 1],
                                             "policy_seed": 10000 + index * 10 + part_index}
    return intake, policy, assets, codes


class RealPeriodRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="period-runtime-legal-", dir=CACHE)
        cls.intake, cls.policy, cls.assets, cls.codes = engineering_period_fixture(Path(cls.folder.name))
        cls.proofs = []

    @classmethod
    def tearDownClass(cls):
        proof = {"scope": "current-pinned-core-period-adapter-engineering-only", "native_executed": True,
                 "historical_rules_verified": False, "official_sources_verified": False,
                 "user_decks_received": False, "completed_proofs": cls.proofs}
        path = CACHE / "pretraining-engine/period-runtime-proof.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        cls.folder.cleanup()

    def test_actual_three_period_assets_and_baselines_load_existing_training_profiles_and_index(self):
        loaded = load_training_inputs(self.intake, self.policy, CACHE, runtime_assets=self.assets)
        index = DataIndex(Path(self.folder.name) / "actual-profile-index")
        for period in PERIODS:
            for purpose in ("train", "validation", "final_eval"):
                selected = loaded.for_runner(period, purpose)
                opponent = self.assets[period].opponent_for(selected["opponent_binding"], selected["profile"])
                self.assertEqual(asdict(opponent.versions), self.assets[period].environment["versions"])
                loaded.freeze_partition(index, period, purpose)
                self.assertFalse(self.assets[period].historical_rules_verified)
        self.assertEqual(index.summary()["datasets"], 9)
        self.assertEqual(index.summary()["artifacts"], 0)
        self.proofs.append({"operation": "actual-assets-baseline-loader-index", "datasets": 9, "training_episodes": 0})

    def test_real_legal_summon_uses_selected_historical_section_and_visible_baselines(self):
        assets = self.assets["2022-07"]
        profile = _profile(DeckParts(tuple(self.codes[:40])), DeckParts(tuple(self.codes[3:43])), 5)
        policies = {seat: assets.bind_rule_opponent(profile, "legal-seat-" + str(seat), seat=seat) for seat in (0, 1)}
        with assets.engine_factory(CACHE, deck_profile=profile, seed=7, selection_key="12" * 16) as engine:
            request = engine.next_decision()
            count = 0
            for _ in range(40):
                self.assertIsNotNone(request)
                self.assertTrue(request.context.versions.banlist.startswith("2022.7:"))
                self.assertIsNone(request.context.seed)
                action = policies[request.observation.observer].select(request)
                engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
                count += 1
                request = engine.next_decision()
                if 61 in engine.messages:
                    break
            self.assertIn(61, engine.messages)
            self.assertEqual(len(engine.callback_errors), 0)
            self.assertEqual(engine.period_context["release_cutoff"], "2022-07-01")
            self.assertFalse(engine.historical_rules_verified)
        self.proofs.append({"operation": "native-legal-normal-summon", "period_label": "2022-07",
                            "responses": count, "historical_rules_verified": False})

    def test_actual_actor_rebind_keeps_engine_profile_and_frozen_driver_consistent(self):
        assets = self.assets["2026-10"]
        profile = _profile(DeckParts(tuple(self.codes[:40])), DeckParts(tuple(self.codes[3:43])), 5)
        before = assets.bind_rule_opponent(profile, "actor-rebind")
        edited = DeckParts((self.codes[59],) + tuple(self.codes[1:40]))
        after = before.rebind(edited, "train")
        self.assertNotEqual(before.binding["own_deck_sha256"], after.binding["own_deck_sha256"])
        with assets.engine_factory(CACHE, deck_profile=after.profile, seed=24, selection_key="34" * 16) as engine:
            request = engine.next_decision()
            self.assertIsNotNone(request)
            self.assertEqual(request.context.versions, after.versions)
            self.assertEqual(tuple(engine.player_decks[0]), edited.main)
        self.proofs.append({"operation": "actual-actor-rebind-native-open", "period_label": "2026-10",
                            "historical_rules_verified": False})

    def test_actual_period_private_v5_discovery_and_exact_keyed_replay(self):
        raw = json.loads((ROOT / "configs/build-xyz-discovery-v3.json").read_text(encoding="utf-8"))
        env = deepcopy(self.intake["environments"]["2026-10"])
        release = Path(self.folder.name) / "private-route-engineering-dates.json"
        release.write_text(json.dumps({"schema_version": 1, "period_id": "2026-10", "release_cutoff": env["release_cutoff"],
            "cards": [{"card_id": code, "ocg_release_date": env["release_cutoff"]} for code in raw["pool"]]}), encoding="utf-8")
        env["releases"] = {"path": str(release.relative_to(CACHE)), "sha256": hashlib.sha256(release.read_bytes()).hexdigest(),
            "source": "engineering-current-physical-files-and-unverified-date-manifest"}
        assets = PeriodBuildAssets(CACHE, "2026-10", env, CACHE, evidence_source="engineering_fixture")
        raw["environment"] = deepcopy(assets.environment)
        task = BuildTask.from_dict(raw)
        main = json.loads((ROOT / "configs/extra-material-engineering-v2.json").read_text(encoding="utf-8"))["decks"][0]
        deck = DeckParts(tuple(main), (task.goal["card_id"],))
        proof = discover_goal(task, deck, assets, seconds=30, attempts=16, branch_budget=64)
        self.assertEqual(proof["status"], "verified_success", proof)
        key = proof["route_evidence"]["private_selection_key_audit_only"]
        self.assertEqual(len(bytes.fromhex(key)), 16)
        self.assertTrue(replay_discovered_goal(task, deck, assets, proof)["replay_verified"])
        self.assertEqual(proof["route_evidence"]["versions"], assets.environment["versions"])
        from ygo_kito.build_training import supervision_projection, validate_supervision
        choices = sorted([deck, *edit_candidates(task, assets, deck)], key=lambda d: engineering_proxy(d, assets))
        worse, better = choices[0], choices[-1]
        data = {"source": "engineering_fixture", "task_sha256": task.sha256,
            "goals": [{"deck": deck.to_dict(), "label": 1., "source": "real_core_conditional_goal", "evidence": proof}],
            "pairs": [{"better": better.to_dict(), "worse": worse.to_dict(),
                "better_value": engineering_proxy(better, assets), "worse_value": engineering_proxy(worse, assets),
                "source": "engineering_mean_printed_attack_proxy_only", "hard_constraints_checked": True}],
            "unknown_routes_used_as_negative": False, "competitive_quality_labels": False,
            "public_effect_receipts": assets.effect_receipts(task)}
        data["supervision_sha256"] = digest(supervision_projection(data))
        validate_supervision(task, assets, data)
        self.assertNotIn(key, json.dumps(supervision_projection(data)))
        incomplete = deepcopy(data)
        del incomplete["goals"][0]["evidence"]["route_evidence"]["private_selection_key_audit_only"]
        with self.assertRaisesRegex(ContractError, "requires its audit selection key"):
            validate_supervision(task, assets, incomplete)
        self.proofs.append({"operation": "actual-period-v5-discovery-keyed-replay", "period_label": "2026-10",
            "goal_status": proof["status"], "branches_executed": proof["route_evidence"]["exploration"]["branches_executed"],
            "historical_rules_verified": False})

    def test_actual_period_registered_baseline_terminal_trace_replays_with_factory(self):
        assets = self.assets["2022-07"]
        profile = _profile(DeckParts(tuple(self.codes[:40])), DeckParts(tuple(self.codes[3:43])), 5)
        policies = {seat: assets.bind_rule_opponent(profile, "terminal-seat-" + str(seat), seat=seat) for seat in (0, 1)}
        audit = []
        with assets.engine_factory(CACHE, deck_profile=profile, seed=7, selection_key="ed" * 16) as engine:
            request = engine.next_decision()
            for _ in range(600):
                if request is None: break
                action = policies[request.observation.observer].select(request)
                audit.append({"player": request.observation.observer, "request_sha256": request_digest(request), "action_id": action.action_id})
                engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
                request = engine.next_decision()
            self.assertIsNone(request, "ordinary baseline duel exceeded its declared fixture decision budget")
            self.assertIsNotNone(engine.outcome)
            self.assertEqual(engine.events[-1]["kind"], 5)
            self.assertEqual(engine.callback_errors, [])
            trace = {"schema_version": 1, "kind": "registered-opponent-private-replay-v1", "name": "engineering-period-baselines",
                "profile": profile, "seed_audit_only": 7, "selection_key_audit_only": engine._selection_seed,
                "resources": engine.receipt, "responses": audit, "events": engine.events, "outcome": engine.outcome,
                "final_observations": [json.loads(json.dumps(asdict(engine._observation(p)))) for p in (0, 1)],
                "result": {"turns": engine.turn, "life_points": engine.life_points}, "opponent_binding": policies[1].binding}
        replayed = replay_private(CACHE, trace, engine_factory=assets.engine_factory)
        self.assertTrue(replayed["replay_verified"])
        self.assertTrue(replayed["natural_terminal"])
        self.assertEqual(replayed["callback_errors"], 0)
        self.proofs.append({"operation": "actual-period-baseline-terminal-private-replay", "period_label": "2022-07",
            "responses": len(audit), "natural_terminal": True, "training_updates": 0, "historical_rules_verified": False})

    def test_actual_repository_host_descriptor_recreates_frozen_baseline_inputs(self):
        # The host descriptor is an actual repository configs path; resources
        # remain the pinned files. Only the declared test dates/roster are synthetic.
        with tempfile.TemporaryDirectory(prefix="period-host-legal-", dir=ROOT / "configs") as folder:
            directory = Path(folder)
            intake, policy = deepcopy(self.intake), deepcopy(self.policy)
            for environment in intake["environments"].values():
                for kind in ("catalog", "releases", "banlist"):
                    environment[kind]["path"] = ".cache/" + environment[kind]["path"]
            (directory / "intake.json").write_text(json.dumps(intake), encoding="utf-8")
            (directory / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
            descriptor = {"schema_version": 1, "period_id": "2022-10",
                "intake": str((directory / "intake.json").relative_to(ROOT)),
                "policy": str((directory / "policy.json").relative_to(ROOT)), "native_roots": {p: ".cache" for p in PERIODS}}
            path = directory / "host.json"
            path.write_text(json.dumps(descriptor), encoding="utf-8")
            host = load_period_host({"period_inputs": str(path.relative_to(ROOT))}, workspace=ROOT)
            selection = host.for_runner("validation")
            opponent = host.opponent_for(selection["opponent_binding"], selection["profile"])
            self.assertEqual(host.period_id, "2022-10")
            self.assertEqual(opponent.versions, selection["versions"])
            self.assertFalse(host.assets.historical_rules_verified)
        self.proofs.append({"operation": "actual-repository-host-input-load", "period_label": "2022-10",
                            "historical_rules_verified": False})

    def test_actual_group_period_inputs_and_conditional_normal_goal_use_same_runtime(self):
        from ygo_kito import group_runner
        from ygo_kito.semantic_curriculum import COURSE, opponent as period_opponent
        from types import SimpleNamespace
        assets = self.assets["2022-10"]
        actor = DeckParts(tuple(self.codes[1:41]))
        minimal = {"schema_version": 1, "name": "trusted-conditional-goal",
                   "decks": [list(actor.main), list(actor.main)]}
        # Select a conditional test goal from a legitimate own opening view.
        # This tests repeatable plumbing, not unbiased draw/strength performance.
        with assets.engine_factory(CACHE, deck_profile=assets.adapt_goal_profile(minimal), seed=7) as engine:
            engine.next_decision()
            goal_card = next(card.card_id for card in engine._observation(0).cards if card.zone == "hand")
        raw = {"schema_version": 1, "task_id": "actual-period-normal-conditional", "environment": assets.environment,
            "goal": {"kind": "normal_summon", "card_id": goal_card,
                     "starting_conditions": {"player": 0, "turn": 1, "requires_opening_hand": [goal_card]}},
            "sizes": {"main": 40, "extra": 0, "side": 0}, "pool": sorted(actor.main),
            "requirements": [{"zone": "main", "card_id": goal_card, "minimum": 1, "maximum": 3}],
            "annotations": [{"tag": "goal·conditional-normal", "layer": "engineering_goal", "subject": "self",
                "source": "engineering-real-own-opening-not-user-deck", "condition": "conditional interface check only"}],
            "source": "engineering_fixture", "candidate_budget": 2}
        normal = BuildTask.from_dict(raw)
        evidence = verify_goal(normal, actor, assets, seconds=30, attempts=1)
        self.assertEqual(evidence["status"], "verified_success")
        self.assertEqual(evidence["task_sha256"], normal.sha256)
        self.assertEqual(evidence["deck_sha256"], digest(actor.to_dict()))
        self.assertTrue(evidence["core_attempts"][0]["declared_opening_condition_met"])
        with tempfile.TemporaryDirectory(prefix="period-group-legal-", dir=ROOT / "configs") as folder:
            directory = Path(folder)
            def save(name, value):
                path = directory / name
                path.write_text(json.dumps(value), encoding="utf-8")
                return str(path.relative_to(ROOT))
            intake, policy = deepcopy(self.intake), deepcopy(self.policy)
            for environment in intake["environments"].values():
                for kind in ("catalog", "releases", "banlist"):
                    environment[kind]["path"] = ".cache/" + environment[kind]["path"]
            part = policy["periods"]["2022-10"]["partitions"]
            part["train"]["seeds"] = [2001, 2002]
            descriptor = {"schema_version": 1, "period_id": "2022-10", "intake": save("intake.json", intake),
                "policy": save("policy.json", policy), "native_roots": {p: ".cache" for p in PERIODS}}
            host_path = save("host.json", descriptor)
            raw.update(schema_version=4, task_id="actual-period-group-counts", requirements=[], goal={
                "kind": "deck_constraints", "constraints": [{"id": "normal-count", "zones": ["main"],
                    "predicate": {"field": "type_all", "value": 17}, "minimum": 40, "maximum": 40}],
                "preferences": [{"id": "explicit-card-count", "zones": ["main"],
                    "predicate": {"field": "card_ids", "value": [goal_card]}, "weight": 1}]})
            task = BuildTask.from_dict(raw)
            heldout = deepcopy(raw)
            heldout["task_id"] = "actual-period-group-heldout"
            heldout["goal"]["constraints"][0]["minimum"] = 39
            course = {"schema_version": 1, "source": COURSE, "period_id": "2022-10", "environment": assets.environment,
                "budget_seconds": 1, "validation_task": save("heldout.json", BuildTask.from_dict(heldout).to_dict())}
            recipe = json.loads((ROOT / "configs/group-runner-v1.json").read_text(encoding="utf-8"))
            recipe.update(period_inputs=host_path, task=save("task.json", task.to_dict()),
                construction_curriculum=save("course.json", course), max_updates=1, bootstrap_seed=2001)
            recipe["train"].update(seed_start=2002, seed_stride=1)
            recipe["validation"].update(seeds=part["validation"]["seeds"], policy_seed=part["validation"]["policy_seed"])
            recipe = group_runner.validate_recipe(recipe)
            profiles, config, actual_task, _, _ = group_runner.inputs(recipe)
            runtime = group_runner.runtime_assets(recipe, CACHE)
            self.assertEqual(actual_task, task)
            self.assertEqual(config.game_seeds, (2002,))
            self.assertEqual(config.policy_seed, part["train"]["policy_seed"])
            self.assertEqual(profiles["train"]["decks"][0], list(actor.main))
            self.assertEqual(runtime.period_context, assets.period_context)
            runtime.validate(task, actor)
            state = SimpleNamespace(row={"recipe": recipe}, phase="bootstrap", sessions=None)
            first = period_opponent(state, profiles["train"], "train")
            state.phase, state.sessions = "duel_train", {"duel": SimpleNamespace(updates=0)}
            second = period_opponent(state, profiles["train"], "train")
            self.assertNotEqual(first.binding["opponent_deck_sha256"], second.binding["opponent_deck_sha256"])
            self.assertEqual(first.binding["own_deck_sha256"], second.binding["own_deck_sha256"])
        self.proofs.append({"operation": "actual-period-group-inputs-and-conditional-normal-goal", "period_label": "2022-10",
            "goal_status": evidence["status"], "bootstrap_seed": 2001, "adaptation_seeds": [2002],
            "two_actual_opponents_selected": True, "training_updates": 0, "historical_rules_verified": False})


if __name__ == "__main__":
    unittest.main()
