"""Period input guards with synthetic files; this module never loads a core."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.data_isolation import opponent_identity
from ygo_kito.opponent_pool import FrozenOpponent
from ygo_kito.period_runtime import PeriodBuildAssets, PeriodNativeEngine
from ygo_kito.validation import ContractError
from tests import test_deck_intake as intake_fixtures
from tests.test_construction_logic import fixture_assets


class PeriodRuntimeGuardTests(unittest.TestCase):
    def setUp(self):
        fixture = intake_fixtures.DeckIntakeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.env = fixture.root, deepcopy(fixture.config["environments"]["2022-07"])
        self.deck = DeckParts.from_dict(fixture.deck)
        self.receipt = {"source_commits": {"core": "a" * 40}, "resources": {
            "cards": self.env["catalog"]["sha256"], "banlist": self.env["banlist"]["sha256"],
            "scripts": "b" * 64, "client_protocol": "c" * 64}}
        def unit_base_init(instance, root):
            instance.root, instance.receipt = Path(root), deepcopy(self.receipt)
            instance.rows = {code: {"id": code, "alias": 1 if code == 21 else 0, "ot": 1,
                "type": 0x41 if code == 22 else 0x4011 if code == 23 else 17, "level": 4,
                "atk": 1000, "def": 1000, "race": 1, "attribute": 1, "setcode": 0,
                "name": "synthetic", "desc": "synthetic printed text"} for code in range(1, 24)}
        # Only static source guards are tested with this mock base. Actual
        # BuildAssets/core composition is in the explicit integration module.
        self.base = patch("ygo_kito.period_runtime.BuildAssets.__init__", unit_base_init)
        self.base.start()
        self.addCleanup(self.base.stop)
        verifier = patch("ygo_kito.period_runtime.verify_resources", side_effect=lambda root: deepcopy(self.receipt))
        verifier.start()
        self.addCleanup(verifier.stop)
        self.assets = PeriodBuildAssets(self.root, "2022-07", self.env, self.root, evidence_source="engineering_fixture")
        self.profile = {"schema_version": 2, "name": "registered-v5-match", "decks": [list(self.deck.main), list(self.deck.main)],
                        "extras": [[], []], "sides": [[], []], "adapter_revision": 5}

    def test_task_and_model_environment_keep_cutoff_and_actual_period_versions(self):
        for kind in ("normal_summon", "synchro_summon", "deck_constraints"):
            self.assertEqual(self.assets.environment_for(kind), self.assets.environment)
        task, _ = fixture_assets()
        raw = task.to_dict()
        raw["environment"] = self.assets.environment_for("normal_summon")
        period_task = BuildTask.from_dict(raw)
        self.assets.check_task(period_task)
        self.assertIsNotNone(period_task.environment["release_cutoff"])
        self.assertFalse(self.assets.historical_rules_verified)

    def test_missing_cutoff_and_mismatched_physical_source_are_closed(self):
        env = deepcopy(self.env)
        env["release_cutoff"] = None
        with self.assertRaises(ContractError):
            PeriodBuildAssets(self.root, "2022-07", env, self.root)
        self.receipt["resources"]["cards"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "actual pinned native resources"):
            PeriodBuildAssets(self.root, "2022-07", self.env, self.root)

    def test_bad_profile_is_rejected_before_parent_loads_a_core(self):
        profile = deepcopy(self.profile)
        profile["decks"][0][0] = 999999999
        with patch("ygo_kito.period_runtime.NativeNormalEngine.__init__", side_effect=AssertionError("must not load core")) as native:
            with self.assertRaises(ContractError):
                PeriodNativeEngine(self.assets, deck_profile=profile)
            native.assert_not_called()
        profile = deepcopy(self.profile)
        profile["adapter_revision"] = 4
        with self.assertRaisesRegex(ContractError, "adapter differs"):
            self.assets.validate_profile(profile)

    def test_trusted_goal_profile_is_framed_without_mutating_any_deck_section(self):
        minimal = {"schema_version": 1, "name": "trusted-verifier-goal",
                   "decks": [list(self.deck.main), list(reversed(self.deck.main))]}
        original = deepcopy(minimal)
        adapted = self.assets.adapt_goal_profile(minimal)
        self.assertEqual(minimal, original)
        self.assertEqual(adapted["decks"], minimal["decks"])
        self.assertEqual(adapted["name"], minimal["name"])
        self.assertEqual(adapted["adapter_revision"], 5)
        self.assertEqual((adapted["extras"], adapted["sides"]), ([[], []], [[], []]))
        self.assertEqual(self.assets.environment["release_cutoff"], self.env["release_cutoff"])
        extended = deepcopy(self.profile)
        extended["adapter_revision"] = 3
        extended["extras"] = [[22], []]
        extended["sides"] = [[20], [19]]
        adapted = self.assets.adapt_goal_profile(extended)
        for section in ("decks", "extras", "sides"):
            self.assertEqual(adapted[section], extended[section])
        self.assertEqual(extended["adapter_revision"], 3)

    def test_framing_cannot_discard_extra_cards_or_relax_engine_revision_guard(self):
        legacy = PeriodBuildAssets(self.root, "2022-07", self.env, self.root,
                                   adapter_revision=1, evidence_source="engineering_fixture")
        extended = deepcopy(self.profile)
        extended["extras"][0] = [22]
        with self.assertRaisesRegex(ContractError, "cannot preserve.*extra deck"):
            legacy.adapt_goal_profile(extended)
        minimal = {"schema_version": 1, "name": "trusted-goal", "decks": self.profile["decks"]}
        with patch("ygo_kito.period_runtime.NativeNormalEngine.__init__", side_effect=AssertionError("no core")) as native:
            with self.assertRaisesRegex(ContractError, "adapter differs"):
                self.assets.engine_factory(self.root, deck_profile=minimal)
            native.assert_not_called()
        self.assets.adapter_revision = 1
        with self.assertRaisesRegex(ContractError, "changed after binding"):
            self.assets.adapt_goal_profile(minimal)

    def test_private_goal_key_is_explicit_validated_and_not_in_supervision_projection(self):
        from ygo_kito.extra_routes import engine_for_goal, route_selection_key
        from ygo_kito.build_training import supervision_projection
        key = "ab" * 16
        with patch.object(self.assets, "engine_factory", return_value="trusted-factory-result") as factory:
            self.assertEqual(engine_for_goal(self.assets, self.deck, 7, selection_key=key), "trusted-factory-result")
            self.assertEqual(factory.call_args.kwargs["selection_key"], key)
            self.assertEqual(factory.call_args.kwargs["deck_profile"]["adapter_revision"], 5)
            for invalid in (None, "bad", 123, "zz" * 16):
                with self.subTest(key=invalid), self.assertRaises(ContractError):
                    route_selection_key(self.assets, self.deck, {"private_selection_key_audit_only": invalid})
        legacy = PeriodBuildAssets(self.root, "2022-07", self.env, self.root,
                                   adapter_revision=2, evidence_source="engineering_fixture")
        with self.assertRaisesRegex(ContractError, "requires a private adapter"):
            engine_for_goal(legacy, self.deck, 7, selection_key=key)
        self.assertIsNone(route_selection_key(legacy, self.deck, {}))
        data = {"task_sha256": "synthetic", "pairs": [], "goals": [{"deck": self.deck.to_dict(), "label": 1,
            "source": "synthetic-projection-only", "evidence": {"status": "synthetic-not-native-proof",
                "trajectory_sha256": "synthetic", "route_evidence": {"private_selection_key_audit_only": key}}}]}
        self.assertNotIn(key, json.dumps(supervision_projection(data)))

    def test_discovery_reuses_one_private_key_across_synthetic_prefix_branches(self):
        from ygo_kito.contracts import DecisionRequest
        from ygo_kito.route_search import discover_goal
        from tests.fixtures import request
        raw = request()
        raw["context"]["seed"] = None
        dto = DecisionRequest.from_dict(raw)
        class PrefixFixture:
            turn, events = 1, []
            def __init__(self): self.cursor = 0
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def next_decision(self):
                self.cursor += 1
                return dto if self.cursor == 1 else None
            def _observation(self, player): return dto.observation
            def submit(self, selection): pass
        task = SimpleNamespace(schema_version=3, pool=(1, 100), goal={"kind": "xyz_summon", "card_id": 100,
            "starting_conditions": {"requires_opening_hand": [1]}})
        assets = SimpleNamespace(rows={100: {"type": 0x800000}}, validate=lambda *args: None)
        assets.adapt_goal_profile = lambda p: dict(p, adapter_revision=5)
        for private in (True, False):
            if not private: del assets.adapt_goal_profile
            with patch("ygo_kito.extra_routes.engine_for_goal", side_effect=lambda *args, **kwargs: PrefixFixture()) as factory, \
                    patch("ygo_kito.route_search.ranked_actions", return_value=dto.actions), \
                    patch("ygo_kito.route_search.completed_special_summon", return_value=False), \
                    patch("ygo_kito.route_search.secrets.token_hex", return_value="cd" * 16) as entropy:
                result = discover_goal(task, self.deck, assets, attempts=1, seconds=1, branch_budget=2)
                self.assertEqual(result["status"], "not_found_within_budget")
                self.assertEqual(factory.call_count, 2)
                self.assertEqual([c.kwargs["selection_key"] for c in factory.call_args_list],
                                 ["cd" * 16 if private else None] * 2)
                self.assertEqual(entropy.call_count, int(private))

    def test_registered_private_replay_forwards_trusted_factory_and_original_key(self):
        from ygo_kito.opponent_pool import replay_private
        trace = {"schema_version": 1, "kind": "registered-opponent-private-replay-v1", "name": "synthetic-forwarding-only",
            "profile": self.profile, "seed_audit_only": 7, "selection_key_audit_only": "de" * 16,
            "resources": self.receipt, "responses": [], "events": [], "outcome": None,
            "final_observations": [], "result": {}, "opponent_binding": {}}
        with patch("ygo_kito.native.NativeNormalEngine", side_effect=AssertionError("must use trusted factory")) as native, \
                patch.object(self.assets, "engine_factory", side_effect=RuntimeError("factory-forwarded")) as factory:
            with self.assertRaisesRegex(RuntimeError, "factory-forwarded"):
                replay_private(self.root, trace, engine_factory=factory)
            native.assert_not_called()
            self.assertEqual(factory.call_args.kwargs["selection_key"], trace["selection_key_audit_only"])
        with self.assertRaisesRegex(ContractError, "factory must be callable"):
            replay_private(self.root, trace, engine_factory="untrusted-path")

    def test_only_actual_implemented_rule_policy_can_be_bound(self):
        opponent = self.assets.bind_rule_opponent(self.profile, "actual-unit-baseline")
        self.assertIsInstance(opponent, FrozenOpponent)
        self.assets.assert_training_opponent(opponent.binding, opponent.profile)
        self.assertIs(self.assets.opponent_for(opponent.binding, opponent.profile), opponent)
        self.assertFalse(opponent.binding["external_provider_verified"])
        self.assertFalse(opponent.historical_rules_verified)
        with self.assertRaises(ContractError):
            self.assets.bind_rule_opponent(self.profile, "unknown-driver", driver_version="unimplemented-provider")
        with self.assertRaises(ContractError):
            self.assets.bind_rule_opponent(self.profile, "promoted", source="user_provided")

    def test_actor_rebind_changes_own_profile_and_preserves_actual_opponent_identity(self):
        original = self.assets.bind_rule_opponent(self.profile, "baseline")
        edited = DeckParts((2,) + self.deck.main[1:])
        revised = original.rebind(edited, "train")
        self.assertNotEqual(original.binding["own_deck_sha256"], revised.binding["own_deck_sha256"])
        self.assertNotEqual(original.binding["profile_sha256"], revised.binding["profile_sha256"])
        self.assertEqual(opponent_identity(original.binding), opponent_identity(revised.binding))
        revised.assert_runtime(self.root, revised.profile, 0)
        with self.assertRaises(ContractError):
            original.assert_runtime(self.root, revised.profile, 0)

    def test_mutated_context_facts_or_binding_never_reuse_original_evidence(self):
        opponent = self.assets.bind_rule_opponent(self.profile, "baseline")
        opponent.binding["driver_version"] = "changed"
        with self.assertRaises(ContractError):
            opponent.assert_runtime(self.root, self.profile, 0)
        self.assets.rows[1]["desc"] = "changed text"
        with self.assertRaisesRegex(ContractError, "changed after binding"):
            self.assets.assert_integrity()


if __name__ == "__main__":
    unittest.main()
