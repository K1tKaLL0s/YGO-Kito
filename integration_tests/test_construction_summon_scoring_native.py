"""Dual-entry (reference & candidate) locked 2022-07 native summon-scoring regressions."""
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_semantics import matches as sem_matches
from ygo_kito.card_identity import rule_name_id
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_layer_flow import ConstructionLayerAdapter, normalize_function_uses
from ygo_kito.construction_layers import LayerContext
from ygo_kito.construction_logic import ConstructionLogic
from ygo_kito.construction_progress import construction_gate
from ygo_kito.construction_relations import InputGroup, Need, RelationContext, Resource, UseRequirement
from ygo_kito.period_runtime import PeriodBuildAssets

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_ROOT.parents[2] if REPO_ROOT.parent.name == "ygo-construction" else REPO_ROOT.parent
DEFAULT_PERIOD_DIR = PROJECT_ROOT / ".cache/optimization-order-03-reference-reuse/v87/period"
DEFAULT_INPUTS_PATH = PROJECT_ROOT / ".cache/construction-optimization-20261114/w02-effect-family-audit/historic-static-inputs.json"
DEFAULT_REG_CACHE = PROJECT_ROOT / ".cache/optimization-order-03-summon-scoring-20261122/reg-cache"
DEFAULT_NATIVE_ROOT = Path(os.environ.get("YGO_KITO_NATIVE_ROOT", "/home/chaos/.local/share/ygo-kito/native"))


class NativeSummonScoringDualEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        period_dir = Path(os.environ.get("YGO_KITO_2207_PERIOD_DIR", str(DEFAULT_PERIOD_DIR)))
        native_root = DEFAULT_NATIVE_ROOT
        inputs_path = Path(os.environ.get("YGO_KITO_2207_INPUTS", str(DEFAULT_INPUTS_PATH)))
        if not (period_dir / "environment.json").is_file() or not native_root.exists() or not inputs_path.is_file():
            raise unittest.SkipTest("Locked 2022-07 period assets, native root, or frozen inputs not present")

        env = json.loads((period_dir / "environment.json").read_text(encoding="utf-8"))
        cls.assets = PeriodBuildAssets(native_root, "2022-07", env, period_dir)
        cls._tmp_reg = None
        reg_cache = Path(os.environ.get("YGO_KITO_2207_REG_CACHE", str(DEFAULT_REG_CACHE)))
        if not reg_cache.exists():
            tmp_base = PROJECT_ROOT / ".cache/optimization-order-03-summon-scoring-20261122/tmp"
            tmp_base.mkdir(parents=True, exist_ok=True)
            cls._tmp_reg = TemporaryDirectory(dir=tmp_base, prefix="native-test-reg-")
            reg_cache = Path(cls._tmp_reg.name)
        cls.assets.native_registration_source.directory = reg_cache

        frozen = json.loads(inputs_path.read_text(encoding="utf-8"))
        cls.frozen = frozen
        cls.task = BuildTask.from_dict(frozen["task"])
        cls.graph = ConstructionLogic.from_dict(frozen["graph"])
        cls.policy = frozen["policy"]
        cls.desc = frozen["reference"]
        cls.binding = CatalogBindingAdapter(cls.assets)
        cls.pool_set = set(cls.task.pool)

        axis_preds = [c["predicate"] for c in cls.task.goal.get("constraints", ()) if c.get("minimum", 0) > 0]
        cls._st_axis = cls._unique(
            lambda r: (r.get("type", 0) & 0x6) != 0 and any(sem_matches(r, p) for p in axis_preds)
        )
        cls._clean_equips = cls._unique(
            lambda r: r.get("type") == 0x40002
            and not any(w in r.get("desc", "") for w in ("特殊召唤", "解放", "不能", "衍生物"))
        )[:40]
        cls._side_st = cls._unique(
            lambda r: r.get("type") == 0x20004
            and not any(w in r.get("desc", "") for w in ("特殊召唤", "解放", "不能", "衍生物"))
        )[:20]
        # Strict Xyz-only non-Rank-4, non-Machine Extra fillers prevent stray Link/Fusion/Synchro/Level leaks
        cls._ex_xyz = cls._unique(
            lambda r: (r.get("type", 0) & 0x800000) != 0
            and (r.get("level", 0) & 255) != 4
            and (r.get("race", 0) & 32) == 0
        )[:25]
        cls._lv4_ns_eff = cls._unique(
            lambda r: (r.get("type", 0) & 0x21) == 0x21
            and not (r.get("type", 0) & 0x48020C0)
            and (r.get("level", 0) & 255) == 4
            and "不能通常召唤" not in r.get("desc", "")
            and "特殊召唤" not in r.get("desc", "")
        )[:3]
        cls._lv4_norm = cls._unique(lambda r: r.get("type") == 0x11 and (r.get("level", 0) & 255) <= 4)[0]
        cls._lv2_norm = cls._unique(lambda r: r.get("type") == 0x11 and (r.get("level", 0) & 255) == 2)[0]
        cls._lv2_effs = cls._unique(
            lambda r: (r.get("type", 0) & 0x21) == 0x21
            and not (r.get("type", 0) & 0x48020C0)
            and (r.get("level", 0) & 255) == 2
        )[:12]
        cls._mach_lv4 = cls._unique(
            lambda r: (r.get("type", 0) & 0x11) == 0x11
            and (r.get("race", 0) & 32) != 0
            and (r.get("level", 0) & 255) <= 4
        )[0]

    @classmethod
    def tearDownClass(cls):
        if cls._tmp_reg is not None:
            cls._tmp_reg.cleanup()

    @classmethod
    def _unique(cls, pred):
        seen, out = set(), []
        for cid in sorted(cls.pool_set):
            row = cls.assets.rows[cid]
            if cls.assets.limits.get(cid, 3) >= 1 and pred(row):
                rn = rule_name_id(cls.assets.rows, cid)
                if rn not in seen:
                    seen.add(rn)
                    out.append(cid)
        return out

    def _pad_clean(self, prefix_main, extra_cards=(), side_cards=()):
        main, extra, side = list(prefix_main), list(extra_cards), list(side_cards)
        ac = Counter(rule_name_id(self.assets.rows, c) for c in main + extra + side)

        def add(lst, cid):
            rn = rule_name_id(self.assets.rows, cid)
            lim = min(3, self.assets.limits.get(cid, 3), self.assets.limits.get(rn, 3))
            if ac[rn] < lim:
                lst.append(cid)
                ac[rn] += 1
                return True
            return False

        for cid in self._ex_xyz:
            if len(extra) >= self.task.sizes["extra"]:
                break
            if cid not in extra_cards:
                add(extra, cid)

        for con in self.task.goal.get("constraints", ()):
            req_min = con.get("minimum", 0)
            pred = con["predicate"]
            cur = sum(1 for c in main if sem_matches(self.assets.rows[c], pred))
            for cid in self._st_axis:
                while cur < req_min and len(main) < self.task.sizes["main"] and sem_matches(self.assets.rows[cid], pred):
                    if add(main, cid):
                        cur += 1
                    else:
                        break

        for cid in self._clean_equips:
            while len(main) < self.task.sizes["main"] and add(main, cid):
                pass
        for cid in self._side_st + self._clean_equips[20:]:
            while len(side) < self.task.sizes["side"] and add(side, cid):
                pass

        deck = DeckParts(main=tuple(main), extra=tuple(extra), side=tuple(side))
        self.assets.validate(self.task, deck)
        return deck

    def _eval_dual_entry(self, deck, *, context=None, policy=None):
        pol = self.policy if policy is None else policy
        adapter = ConstructionLayerAdapter(
            self.binding,
            context_provider=(lambda _t, _g: context) if context is not None else None,
        )
        inv = deck.to_dict()
        custom_ref = {**self.desc, "deck": inv}
        custom_desc = {**pol["pass"]["reference"], "deck_sha256": digest(inv)}
        _, _, ref_opts = adapter.reference_inputs(
            self.task, self.graph, custom_ref, custom_desc, policy=pol
        )
        q_ref, work_r, stop_r = adapter.evaluate_inventory(self.task, deck, should_stop=lambda: False, **ref_opts)
        self.assertIsNone(work_r)
        self.assertIsNone(stop_r)

        selected, results, trace = adapter.evaluate(
            self.task, self.graph, [{"deck": deck}], {}, [0], context=context, policy=pol
        )
        self.assertEqual(selected, [0])
        self.assertTrue(trace["selection_complete"])
        q_cand = results[0]["quality_evaluation"]
        layer_cand = results[0]["layer_evaluation"]

        self.assertEqual(q_ref["score"], q_cand["score"])
        self.assertEqual(q_ref["stages"], q_cand["stages"])
        self.assertEqual(q_ref["total"], q_cand["total"])
        self.assertEqual(q_ref.get("hard_requirements"), q_cand.get("hard_requirements"))
        return q_ref, q_cand, layer_cand

    def _resident_ops(self, quality, card_id):
        return sorted(
            [
                (
                    (v.get("operation") or {}).get("kind"),
                    v["relation"]["status"],
                    v.get("special_summon_supported"),
                    tuple(v["relation"].get("unknown", ())),
                    json.dumps(v["relation"].get("condition_expression", ()), sort_keys=True),
                )
                for k, v in quality["use_details"].items()
                if v.get("card_id") == card_id and not k.endswith((":going_first", ":going_second"))
            ],
            key=lambda x: (str(x[0]), x[1], str(x[2])),
        )

    def _assert_card_status_dual(self, deck, card_id, expected_status, *, expected_ss=None, context=None):
        q_ref, q_cand, _ = self._eval_dual_entry(deck, context=context)
        ref_ops = self._resident_ops(q_ref, card_id)
        cand_ops = self._resident_ops(q_cand, card_id)
        self.assertEqual(ref_ops, cand_ops)
        self.assertTrue(ref_ops, f"Expected resident operations for card {card_id}")
        self.assertTrue(any(row[1] == expected_status for row in ref_ops), (card_id, expected_status, ref_ops))
        if expected_ss is not None:
            self.assertTrue(any(row[2] is expected_ss for row in ref_ops), (card_id, expected_ss, ref_ops))
        return q_ref, q_cand, ref_ops

    def test_dweller_three_controls_gigantes_instant_fusion_and_side_negative(self):
        dweller = 21044178
        thrasher = 65367484
        rat = 549481

        # 1. Two Photon Thrashers cannot double-enter on empty own MZONE to Xyz Dweller
        self._assert_card_status_dual(self._pad_clean([thrasher, thrasher], (dweller,)), dweller, "missing")
        # 2. Thrasher (empty SS) + Rat (NS) -> Dweller supported
        self._assert_card_status_dual(self._pad_clean([thrasher, rat], (dweller,)), dweller, "supported")
        # 3. Two NS-only Lv4 -> Dweller missing
        self._assert_card_status_dual(self._pad_clean([rat, self._lv4_ns_eff[0]], (dweller,)), dweller, "missing")
        # 4. Gigantes (71544954 banishing EARTH 25926710) + Thrasher + Mudora (81439173) -> Dweller supported
        self._assert_card_status_dual(
            self._pad_clean([thrasher, 71544954, 25926710, 81439173], (dweller,)), dweller, "supported"
        )
        # 5. Instant Fusion (1845204) + Mudragon (54757758) + Rat -> Dweller supported; removing Mudragon -> missing
        self._assert_card_status_dual(self._pad_clean([rat, 1845204], (dweller, 54757758)), dweller, "supported")
        self._assert_card_status_dual(self._pad_clean([rat, 1845204], (dweller,)), dweller, "missing")
        # 6. Side-only 2nd Lv4 -> resident Dweller missing
        self._assert_card_status_dual(self._pad_clean([thrasher], (dweller,), (rat,)), dweller, "missing")

    def test_ritual_multi_material_positive_three_material_negative_and_budget_unknown(self):
        # End of the World (8198712) + Demise Lv8 (72426662) + 4x Lv2 = 8 -> supported
        d_pos = self._pad_clean([8198712, 72426662, 93920745, 93920745, 93920745, self._lv2_norm])
        self._assert_card_status_dual(d_pos, 8198712, "supported")
        self._assert_card_status_dual(d_pos, 72426662, "supported")

        # 3x Lv2 = 6 != 8 (with zero-level Xyz-only Extra fillers) -> missing
        d_neg = self._pad_clean([8198712, 72426662, 93920745, 93920745, 93920745])
        self._assert_card_status_dual(d_neg, 8198712, "missing")
        self._assert_card_status_dual(d_neg, 72426662, "missing")

        # Budget-exhausted incomplete ritual: Advanced Ritual Art (46052429, Normal only) + Lv2 Effect monsters -> unknown
        lv2_swarm = [c for c in self._lv2_effs[:10] for _ in range(3)][:25]
        d_trunc = self._pad_clean([46052429, 72426662] + lv2_swarm)
        _, _, ops_rit = self._assert_card_status_dual(d_trunc, 46052429, "unknown")
        self.assertTrue(any("ritual_material_search_incomplete" in r[3] for r in ops_rit), ops_rit)

    def test_zeus_battle_precondition_and_joint_material_consumption(self):
        zeus = 90448279
        thrasher = 65367484
        rat = 549481
        dweller = 21044178
        castel = 82633039

        # Standalone Zeus requires xyz_monster_battled_this_turn external precondition and detaches 2 for send_grave
        d_solo = self._pad_clean([thrasher, rat], (dweller, zeus))
        q_ref, _, z_ops = self._assert_card_status_dual(d_solo, zeus, "supported")
        self.assertTrue(
            any(r[0] == "send_grave" and r[1] == "supported" and "xyz_monster_battled_this_turn" in r[4] for r in z_ops),
            z_ops,
        )

        # Joint check via LayerContext: Dweller (detach 1) + Zeus (detach 2) feasible;
        # Castel change_position (detach 1) + Zeus (detach 2) feasible;
        # Castel return_deck (detach 2) + Zeus (detach 2) conflicts!
        cat = self.binding.semantic_catalog
        for xyz_id, expect_by_kind in ((dweller, {"prevent_activation": True}), (castel, {"change_position": True, "return_deck": False})):
            d_pair = self._pad_clean([thrasher, rat], (xyz_id, zeus))
            f0 = normalize_function_uses(self.task, d_pair, cat, policy=self.policy)
            u_zeus = [
                u for u in f0["uses"]
                if f0["use_details"][u.use_id]["card_id"] == zeus
                and (f0["use_details"][u.use_id].get("operation") or {}).get("kind") == "send_grave"
                and not u.use_id.endswith((":going_first", ":going_second"))
            ]
            z_fid = f0["use_details"][u_zeus[0].use_id]["relation_fact_id"]
            u_base = [
                u for u in f0["uses"]
                if f0["use_details"][u.use_id]["card_id"] == xyz_id
                and not u.use_id.endswith((":going_first", ":going_second"))
            ]
            for bu in u_base:
                det = f0["use_details"][bu.use_id]
                op_kind = (det.get("operation") or {}).get("kind")
                if op_kind not in expect_by_kind:
                    continue
                pair_ctx = LayerContext(
                    self.task,
                    self.graph,
                    (),
                    relations=RelationContext(
                        (
                            UseRequirement(
                                "joint:pair",
                                InputGroup(
                                    "all",
                                    (
                                        Need("ja", Resource("functional_operation", attributes=(det["relation_fact_id"],)), mode="presence"),
                                        Need("jb", Resource("functional_operation", attributes=(z_fid,)), mode="presence"),
                                    ),
                                ),
                                "joint xyz+zeus",
                                required=True,
                            ),
                        ),
                        (),
                        constraints=(),
                    ),
                )
                pair_policy = {
                    **self.policy,
                    "pass": {
                        **self.policy["pass"],
                        "reference": {
                            **self.policy["pass"]["reference"],
                            "deck_sha256": digest(d_pair.to_dict()),
                        },
                    },
                }
                q_r, q_c, layer_c = self._eval_dual_entry(d_pair, context=pair_ctx, policy=pair_policy)
                req_r = {h["requirement_id"]: h["status"] for h in q_r["hard_requirements"]}
                req_c = {h["requirement_id"]: h["status"] for h in q_c["hard_requirements"]}
                expected_status = "satisfied" if expect_by_kind[op_kind] else "failed"
                self.assertEqual(req_r.get("joint_required"), expected_status, (xyz_id, op_kind, req_r))
                self.assertEqual(req_c.get("joint_required"), expected_status, (xyz_id, op_kind, req_c))
                gate_c = construction_gate(
                    self.task, d_pair, self.assets, layer_c, policy=pair_policy, quality=q_c, reference_quality=q_r
                )
                if not expect_by_kind[op_kind]:
                    self.assertIn("required_function:joint_required:failed", gate_c["reasons"])
                else:
                    self.assertNotIn("required_function:joint_required:failed", gate_c["reasons"])

    def test_seven_summon_matrix_positive_and_negative(self):
        thrasher = 65367484
        rat = 549481

        # 1. Normal / Tribute Summon: Caius (9748752)
        self._assert_card_status_dual(self._pad_clean([9748752, thrasher]), 9748752, "supported")
        self._assert_card_status_dual(self._pad_clean([9748752, rat]), 9748752, "missing")

        # 2. Flip Summon: Penguin Soldier (93920745) in Main vs Side-only
        self._assert_card_status_dual(self._pad_clean([93920745]), 93920745, "supported", expected_ss=False)
        q_side_ref, q_side_cand, _ = self._eval_dual_entry(self._pad_clean([], (), (93920745,)))
        self.assertEqual(self._resident_ops(q_side_ref, 93920745), [])
        self.assertEqual(self._resident_ops(q_side_cand, 93920745), [])

        # 3. Fusion (Instant Fusion & Contact Fusion)
        # Instant Fusion pos/neg verified with Mudragon -> Dweller; plus Contact Fusion Fortress (79229522)
        d_cf_pos = self._pad_clean([70095154, self._mach_lv4], (79229522,))
        st_cf_pos = self.assets.native_registration_source.summon_stock(list(d_cf_pos.main), list(d_cf_pos.extra), {}, {}, alternate=True)
        self.assertTrue(any(row["target"] == 79229522 for row in st_cf_pos.get("contact_fusion", ())))
        d_cf_neg = self._pad_clean([70095154], (79229522,), (self._mach_lv4,))
        st_cf_neg = self.assets.native_registration_source.summon_stock(list(d_cf_neg.main), list(d_cf_neg.extra), {}, {}, alternate=True)
        self.assertEqual(st_cf_neg.get("contact_fusion", []), [])

        # 4. Synchro: Clear Wing (82044279 Lv7) with Ash Lv3 Tuner vs no Tuner
        self._assert_card_status_dual(self._pad_clean([thrasher, 14558127], (82044279,)), 82044279, "supported", expected_ss=True)
        self._assert_card_status_dual(self._pad_clean([thrasher, rat], (82044279,)), 82044279, "missing", expected_ss=False)

        # 5. Link: Link Spider (98978921) with 2x Normal vs 0 Normal + Link Rating/Arrows (Apollousa 4280258 + Phoenix 2857636)
        self._assert_card_status_dual(self._pad_clean([self._lv4_norm, self._lv4_norm], (98978921,)), 98978921, "supported", expected_ss=True)
        self._assert_card_status_dual(self._pad_clean([rat], (98978921,)), 98978921, "missing")
        d_lchain = self._pad_clean([self._lv4_norm, self._lv4_norm, 1845204, 2460565], (54757758, 98978921, 2857636, 4280258))
        st_lchain = self.assets.native_registration_source.summon_stock(list(d_lchain.main), list(d_lchain.extra), {}, {}, alternate=True)
        link_targets = {row["target"] for row in st_lchain.get("link", ())}
        self.assertTrue({98978921, 2857636, 4280258} <= link_targets, link_targets)

        # 6. Pendulum: 11609969 (Scale 10) + 46796664 (Scale 1) + 28406301 (draw when Pendulum summoned) vs 1 scale
        self._assert_card_status_dual(self._pad_clean([11609969, 46796664, 28406301, 28406301]), 28406301, "supported")
        q_p1_r, q_p1_c, _ = self._eval_dual_entry(self._pad_clean([11609969, 28406301, 28406301]))
        self.assertEqual(self._resident_ops(q_p1_r, 28406301), self._resident_ops(q_p1_c, 28406301))
        self.assertTrue(any(r[0] == "draw" and r[1] == "missing" for r in self._resident_ops(q_p1_r, 28406301)))

    def test_ddd_cross_summon_chain_positive_and_negative_controls(self):
        # Gate (46372010) + Kepler (11609969) + Copernicus (46796664) + Gryphon (28406301)
        # + Gilgamesh (9024198 Link-2) + Wave King Caesar (3758046 Rank-4 Xyz)
        # Also include LP-cost card 197042 to guard _restriction_match resource-only costs under Gilgamesh lock
        d_ddd_pos = self._pad_clean(
            [46372010, 11609969, 11609969, 46796664, 46796664, 28406301, 28406301, 28406301, 197042],
            (9024198, 3758046),
        )
        q_r, _, _ = self._eval_dual_entry(d_ddd_pos)
        for cid, op_kind in ((46372010, "search"), (9024198, "special_summon"), (9024198, "place_pendulum_scales"), (28406301, "draw"), (3758046, "special_summon")):
            ops = self._resident_ops(q_r, cid)
            self.assertTrue(any(o[0] == op_kind and o[1] == "supported" for o in ops), (cid, op_kind, ops))

        # Negative 1: Scales (11609969, 46796664) moved to Side -> Gilgamesh scale placement missing in resident scope
        d_side_scales = self._pad_clean([46372010, 28406301, 28406301], (9024198, 3758046), (11609969, 46796664))
        q_s_r, _, _ = self._eval_dual_entry(d_side_scales)
        self.assertTrue(
            any(o[0] == "place_pendulum_scales" and o[1] == "missing" for o in self._resident_ops(q_s_r, 9024198))
        )

        # Negative 2: Single D/D monster (1x 28406301) -> Gilgamesh & Caesar special_summon missing
        d_single = self._pad_clean([46372010, 28406301], (9024198, 3758046))
        self._assert_card_status_dual(d_single, 9024198, "missing")
        self._assert_card_status_dual(d_single, 3758046, "missing", expected_ss=False)

    def test_no_replay_and_card_text_disabled_invariance(self):
        d_base = self._pad_clean([65367484, 549481], (21044178,))
        q_ref_base, q_cand_base, _ = self._eval_dual_entry(d_base)

        orig_descs = {cid: row["desc"] for cid, row in self.assets.rows.items()}
        try:
            for row in self.assets.rows.values():
                row["desc"] = ""
            # Disable NativeNormalEngine replay AND strip all query receipts (no-replay) with wiped card texts
            with ExitStack() as stack:
                stack.enter_context(patch("ygo_kito.native.NativeNormalEngine", side_effect=AssertionError("replay disallowed")))
                orig_eval = self.assets.construction_rules.evaluate
                stack.enter_context(
                    patch.object(
                        self.assets.construction_rules,
                        "evaluate",
                        side_effect=lambda *a, **kw: {**orig_eval(*a, **kw), "status": "complete", "receipts": [], "pending": []},
                    )
                )
                self.binding = CatalogBindingAdapter(self.assets)
                q_ref_inv, q_cand_inv, _ = self._eval_dual_entry(d_base)
        finally:
            for cid, text in orig_descs.items():
                self.assets.rows[cid]["desc"] = text
            self.binding = CatalogBindingAdapter(self.assets)

        for key in ("score", "stages", "total"):
            self.assertEqual(q_ref_base[key], q_ref_inv[key])
            self.assertEqual(q_cand_base[key], q_cand_inv[key])
        self.assertEqual(self._resident_ops(q_ref_base, 21044178), self._resident_ops(q_ref_inv, 21044178))
        self.assertEqual(self._resident_ops(q_cand_base, 21044178), self._resident_ops(q_cand_inv, 21044178))


if __name__ == "__main__":
    unittest.main()
