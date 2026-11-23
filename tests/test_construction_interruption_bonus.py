"""CPU unit tests for v5 interruption bonus math, capacity/Side rules, bounds, and checkpoint restore."""
from copy import deepcopy
from dataclasses import replace
from math import log2
import json
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.construction_layer_flow import NORMALIZATION_VERSION, functional_asset_version
from ygo_kito.construction_logic import ConstructionLogic, ConstructionSession, LogicNode, LogicTag
from ygo_kito.construction_progress import (
    host_construction_quality,
    restore_progress,
    revise_quality_policy,
)
from ygo_kito.construction_quality import (
    FUNCTIONAL_QUALITY_VERSION,
    FUNCTIONAL_QUALITY_VERSION_V5,
    FUNCTIONAL_SCOPE,
    FUNCTION_DICTIONARY_VERSION,
    INTERRUPTION_HAS_WEIGHT,
    INTERRUPTION_SUPPORTED_WEIGHT,
    evaluate_functional_quality,
    functional_quality_config,
)
from ygo_kito.effect_mechanisms import MechanismCatalog
from ygo_kito.validation import ContractError
from tests.test_construction_functional_quality import fixture, use
from tests.test_construction_layer_flow import flow_fixture


def v5_policy(*, budget=4096):
    return {
        "version": "test-functional-v5",
        "source": "static-fixture",
        "metrics": [],
        "quality": {
            "evaluator_version": FUNCTIONAL_QUALITY_VERSION_V5,
            "function_dictionary_version": FUNCTION_DICTIONARY_VERSION,
            "theme_rules": [],
            "side_directions": {"going_first": 0.5, "going_second": 0.5},
            "required_scope": list(FUNCTIONAL_SCOPE),
            "completion_budget": budget,
            "interruption_bonus": {
                "has_interruption_weight": INTERRUPTION_HAS_WEIGHT,
                "supported_interruption_weight": INTERRUPTION_SUPPORTED_WEIGHT,
            },
        },
        "pass": {"mode": "none"},
    }


def v4_policy(*, budget=4096):
    return {
        "version": "test-functional-v4",
        "source": "static-fixture",
        "metrics": [],
        "quality": {
            "evaluator_version": FUNCTIONAL_QUALITY_VERSION,
            "function_dictionary_version": FUNCTION_DICTIONARY_VERSION,
            "theme_rules": [],
            "side_directions": {"going_first": 0.5, "going_second": 0.5},
            "required_scope": list(FUNCTIONAL_SCOPE),
            "completion_budget": budget,
        },
        "pass": {"mode": "none"},
    }


def int_use(key="u", sources=("main:1:1",), family="disrupt", condition=True, *, is_interruption=True, **options):
    return use(key, sources=sources, family=family, condition=condition, is_interruption=is_interruption, **options)


class ConstructionInterruptionBonusTests(unittest.TestCase):
    def test_v5_policy_validation_and_v4_rejection(self):
        cfg_v5 = functional_quality_config(v5_policy()["quality"])
        self.assertEqual(cfg_v5["evaluator_version"], FUNCTIONAL_QUALITY_VERSION_V5)
        self.assertAlmostEqual(cfg_v5["interruption_bonus"]["has_interruption_weight"], 0.30)
        self.assertAlmostEqual(cfg_v5["interruption_bonus"]["supported_interruption_weight"], 0.20)

        bad_v4 = deepcopy(v4_policy()["quality"])
        bad_v4["interruption_bonus"] = {"has_interruption_weight": 0.30, "supported_interruption_weight": 0.20}
        with self.assertRaises(ContractError):
            functional_quality_config(bad_v4)

        bad_weights = deepcopy(v5_policy()["quality"])
        bad_weights["interruption_bonus"]["has_interruption_weight"] = 0.25
        with self.assertRaises(ContractError):
            functional_quality_config(bad_weights)

    def test_exact_main_40_values_and_45_card_scaling(self):
        expected_40 = {1: 0.5000, 2: 0.7680, 3: 0.9630}
        for n in (1, 2, 3):
            main = [1] * n + list(range(2, 42 - n))
            uses = [int_use(f"u{i}", sources=(f"main:1:{i}",), family=f"f{i}") for i in range(1, n + 1)]
            layer, facts = fixture(uses, main=main)
            q4 = evaluate_functional_quality(layer, policy=v4_policy(), facts=facts)
            q5 = evaluate_functional_quality(layer, policy=v5_policy(), facts=facts)
            bonus = q5["interruption_bonus"]["resident"]
            self.assertAlmostEqual(bonus["total"], expected_40[n], places=4)
            self.assertAlmostEqual(q5["score"]["value"] - q4["score"]["value"], bonus["total"], places=9)
            self.assertAlmostEqual(bonus["tier1_total"], 0.30 * log2(1 + (1.0 if n == 1 else 1.0 + 0.9 * (n - 1))), places=9)
            self.assertAlmostEqual(bonus["tier2_total"], 0.20 * log2(1 + (1.0 if n == 1 else 1.0 + 0.9 * (n - 1))), places=9)

        # 45-card Main N-scaling: 40 * E_main(k) / 45
        main45 = [1, 1] + list(range(2, 45))
        uses45 = [int_use("u1", sources=("main:1:1",), family="f1"), int_use("u2", sources=("main:1:2",), family="f2")]
        layer45, facts45 = fixture(uses45, main=main45)
        q45_5 = evaluate_functional_quality(layer45, policy=v5_policy(), facts=facts45)
        expected_b45 = log2(1.0 + (40.0 / 45.0) * (1.0 + 0.9))
        self.assertAlmostEqual(q45_5["interruption_bonus"]["resident"]["total"], 0.50 * expected_b45, places=9)

    def test_extra_decay_zero_capacity_and_per_copy_deduplication(self):
        main = list(range(1, 41))
        # Extra 0.8 decay for 2 Extra copies (same name 101)
        uses_ex = [
            replace(int_use(f"e{i}", sources=(f"extra:101:{i}",)), valuation_mode="called")
            for i in (1, 2)
        ]
        layer_ex, facts_ex = fixture(uses_ex, main=main, extra=[101, 101])
        q_ex = evaluate_functional_quality(layer_ex, policy=v5_policy(), facts=facts_ex)
        self.assertAlmostEqual(q_ex["interruption_bonus"]["resident"]["total"], 0.50 * log2(1.0 + 1.0 + 0.8), places=9)

        # Extra capacity=0: no Extra copies physically present -> tier1 & tier2 must be 0
        layer_cap0, facts_cap0 = fixture([], main=main, extra=[])
        q_cap0 = evaluate_functional_quality(layer_cap0, policy=v5_policy(), facts=facts_cap0)
        self.assertEqual(q_cap0["interruption_bonus"]["resident"]["total"], 0.0)

        # Multiple interruption uses pointing to the SAME card copy count ONCE per copy per tier
        uses_dup = [
            int_use("i1", sources=("main:1:1",), family="f1"),
            int_use("i2", sources=("main:1:1",), family="f2"),
        ]
        layer_dup, facts_dup = fixture(uses_dup, main=main)
        q_dup = evaluate_functional_quality(layer_dup, policy=v5_policy(), facts=facts_dup)
        self.assertAlmostEqual(q_dup["interruption_bonus"]["resident"]["total"], 0.5000, places=9)
        grp = next(iter(q_dup["interruption_bonus"]["resident"]["groups"].values()))
        self.assertEqual(grp["has_count"], 1)
        self.assertEqual(grp["supported_count"], 1)

    def test_missing_support_and_unsupported_third_copy_and_d1_loss(self):
        # Tier 1 (+30%) still counts when card is present as interruption, while unsupported condition suppresses Tier 2 (+20%) and emits stage='self' loss
        main = [1, 1, 1] + list(range(2, 39))
        uses = [
            int_use("u1", sources=("main:1:1",), family="f1", condition=True),
            int_use("u2", sources=("main:1:2",), family="f2", condition=True),
            int_use("u3", sources=("main:1:3",), family="f3", condition=False),
        ]
        layer, facts = fixture(uses, main=main)
        q_v5 = evaluate_functional_quality(layer, policy=v5_policy(), facts=facts)
        bonus = q_v5["interruption_bonus"]["resident"]
        grp = next(iter(bonus["groups"].values()))
        self.assertEqual(grp["has_count"], 3)
        self.assertEqual(grp["supported_count"], 2)
        self.assertAlmostEqual(bonus["tier1_total"], 0.30 * log2(1.0 + 1.0 + 0.9 + 0.9), places=9)
        self.assertAlmostEqual(bonus["tier2_total"], 0.20 * log2(1.0 + 1.0 + 0.9), places=9)

        # Single completely unsupported interruption card: Tier 1 = 0.30, Tier 2 = 0.0, D1 ('self') interruption_supported loss recorded
        layer_1_bad, facts_1_bad = fixture([int_use("u1", sources=("main:1:1",), condition=False)], main=list(range(1, 41)))
        q_1_bad = evaluate_functional_quality(layer_1_bad, policy=v5_policy(), facts=facts_1_bad)
        self.assertAlmostEqual(q_1_bad["interruption_bonus"]["resident"]["tier1_total"], 0.30, places=9)
        self.assertAlmostEqual(q_1_bad["interruption_bonus"]["resident"]["tier2_total"], 0.0, places=9)
        self.assertTrue(any(
            row.get("stage") == "self" and row.get("channel_id") == "interruption_supported" and row.get("lower", 0.0) > 0.0
            for row in q_1_bad["loss_records"]
        ))

    def test_side_combined_name_count_without_reset_and_slot_tradeoff_and_unknown_bounds(self):
        # Side combined count combines main:1:1 + side:1:1 (both destination='main') in going_second (m=2 without resetting 1st copy!)
        main = [1] + list(range(2, 41))
        side = [1] + list(range(101, 115))
        uses = [
            int_use("u_main", sources=("main:1:1",), family="f1", condition=True),
            int_use("u_side", sources=("side:1:1",), family="f2", condition=True, scope_id="going_second"),
        ]
        layer, facts = fixture(uses, main=main, side=side)
        q_side = evaluate_functional_quality(layer, policy=v5_policy(), facts=facts)
        res_tot = q_side["interruption_bonus"]["resident"]["total"]
        gs_tot = q_side["interruption_bonus"]["directions"]["going_second"]["total"]
        self.assertAlmostEqual(res_tot, 0.5000, places=9)
        self.assertAlmostEqual(gs_tot, 0.7680, places=4)
        self.assertGreater(gs_tot, res_tot)

        # Equal-size slot tradeoff: swapping plain filler for supported interruption increases v5 score by +0.5000 beyond base gain
        plain_u = use("plain", sources=("main:1:1",), family="plain", condition=True)
        int_u = int_use("int", sources=("main:2:1",), family="plain", condition=True)
        l_plain, f_plain = fixture([plain_u], main=main)
        l_int, f_int = fixture([int_u], main=main)
        q_plain = evaluate_functional_quality(l_plain, policy=v5_policy(), facts=f_plain)
        q_int = evaluate_functional_quality(l_int, policy=v5_policy(), facts=f_int)
        self.assertAlmostEqual(q_int["score"]["value"] - q_plain["score"]["value"], 0.5000, places=9)

        # Exact & relaxed component unknown bounds: tier 1 is certain (+0.30), tier 2 depends on unknown 'u' (+0.00 to +0.20)
        layer_u, facts_u = fixture(
            [int_use("unk", sources=("main:1:1",), family="f_unk", condition="u")],
            main=main, variables={"u": None},
        )
        q_u = evaluate_functional_quality(layer_u, policy=v5_policy(), facts=facts_u)
        self.assertEqual(q_u["score"]["bound_kind"], "exact")
        self.assertAlmostEqual(q_u["score"]["lower"], 0.30, places=9)
        self.assertAlmostEqual(q_u["score"]["upper"], 1.50, places=9)  # 1.0 base + 0.30 tier1 + 0.20 tier2

        # Trigger component relaxation (completion_budget=2 with >2 unknown variables in one component)
        vars3 = {"u1": None, "u2": None, "u3": None}
        layer_c, facts_c = fixture(
            [int_use("unkc", sources=("main:1:1",), family="f_unkc", condition={"all": list(vars3)})],
            main=main, variables=vars3,
        )
        q_c = evaluate_functional_quality(layer_c, policy=v5_policy(budget=2), facts=facts_c)
        self.assertAlmostEqual(q_c["score"]["lower"], 0.30, places=9)
        self.assertAlmostEqual(q_c["score"]["upper"], 1.50, places=9)

    def test_host_policy_and_checkpoint_restore_across_v4_and_v5(self):
        task, assets, _, _, decks, _ = flow_fixture()
        deck = decks[0]
        p_v4, _ = host_construction_quality(task, interruption_bonus=False)
        p_v5, _ = host_construction_quality(task, interruption_bonus=True)
        self.assertEqual(p_v4["quality"]["evaluator_version"], FUNCTIONAL_QUALITY_VERSION)
        self.assertNotIn("interruption_bonus", p_v4["quality"])
        self.assertEqual(p_v5["quality"]["evaluator_version"], FUNCTIONAL_QUALITY_VERSION_V5)
        self.assertEqual(p_v5["quality"]["interruption_bonus"], {"has_interruption_weight": 0.30, "supported_interruption_weight": 0.20})

        graph = ConstructionLogic("g", (LogicNode("n", (LogicTag("effect", "e"),)),), (), ("n",), ("n",))
        asset_version = functional_asset_version(MechanismCatalog(assets, task.pool))
        layer = dict(axis=dict(inventory=deck.to_dict(), task=task.to_dict(), logic=graph.to_dict()))
        facts = dict(
            version="construction-quality-facts-v1",
            task_sha256=task.sha256,
            deck_sha256=digest(deck.to_dict()),
            asset_version=asset_version,
            normalization_version=NORMALIZATION_VERSION,
            uses=[],
            impacts=[],
            variables={},
            constraints=[],
            coverage={f"{z}:{c}": "evaluated" for z in ("main", "extra", "side") for c in getattr(deck, z)},
            scope_status={k: "evaluated" for k in FUNCTIONAL_SCOPE},
            source_aliases={},
        )
        q5 = evaluate_functional_quality(layer, policy=p_v5, facts=facts)
        deck_sha = digest(deck.to_dict())
        logic_sha = digest(graph.to_dict())
        state_v5 = {
            "schema_version": 3,
            "task_sha256": task.sha256,
            "logic_sha256": logic_sha,
            "asset_version": asset_version,
            "status": "optimizing",
            "iteration": 1,
            "candidate_version": 1,
            "quality_policy": deepcopy(p_v5),
            "handoffs": [{
                "role": "build_goal",
                "input_deck_sha256": None,
                "output_deck_sha256": deck_sha,
                "candidate_version": 1,
            }],
            "candidate": {
                "deck": deck.to_dict(),
                "deck_sha256": deck_sha,
                "layer_evaluation": layer,
                "quality_evaluation": q5,
                "evaluation_status": "evaluated",
            },
            "retained_candidates": [],
        }
        payload = json.loads(json.dumps(state_v5))

        # v5 -> v5 restore keeps evaluation intact
        s_same = ConstructionSession("test v5->v5", task)
        s_same.submit_logic(graph, role="build_goal", reason="test")
        restore_progress(s_same, deepcopy(payload), assets)
        self.assertEqual(s_same.construction_progress["candidate"]["evaluation_status"], "evaluated")
        self.assertEqual(
            s_same.construction_progress["candidate"]["quality_evaluation"]["version"],
            FUNCTIONAL_QUALITY_VERSION_V5,
        )

        # v5 -> v4 version switch invalidates v5 quality cleanly
        revise_quality_policy(s_same, p_v4)
        self.assertEqual(s_same.construction_progress["candidate"]["evaluation_status"], "stale")
        self.assertNotIn("quality_evaluation", s_same.construction_progress["candidate"])

        # Mismatched policy vs candidate version in saved JSON marks stale cleanly on restore
        q4 = evaluate_functional_quality(layer, policy=p_v4, facts=facts)
        payload_mixed = deepcopy(payload)
        payload_mixed["candidate"]["quality_evaluation"] = q4
        s_upgrade = ConstructionSession("test v4->v5 mismatch", task)
        s_upgrade.submit_logic(graph, role="build_goal", reason="test")
        restore_progress(s_upgrade, payload_mixed, assets)
        self.assertEqual(s_upgrade.construction_progress["candidate"]["evaluation_status"], "stale")
        self.assertEqual(s_upgrade.construction_progress["stop_reason"], "quality_reevaluation_required")

        # v4 -> v5 revise_quality_policy cleanly migrates saved v4 session
        payload_v4 = deepcopy(payload)
        payload_v4["quality_policy"] = deepcopy(p_v4)
        payload_v4["candidate"]["quality_evaluation"] = q4
        s_v4 = ConstructionSession("test v4->v5", task)
        s_v4.submit_logic(graph, role="build_goal", reason="test")
        restore_progress(s_v4, payload_v4, assets)
        self.assertEqual(s_v4.construction_progress["candidate"]["evaluation_status"], "evaluated")
        revise_quality_policy(s_v4, p_v5)
        self.assertEqual(s_v4.construction_progress["candidate"]["evaluation_status"], "stale")


if __name__ == "__main__":
    unittest.main()
