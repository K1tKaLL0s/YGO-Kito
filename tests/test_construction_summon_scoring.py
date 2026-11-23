"""CPU unit contracts for summon stock parsing, empty-own-MZONE DAG pools, rituals, and Zeus material inheritance."""
from collections import Counter
from types import SimpleNamespace
import unittest

from ygo_kito.build_contracts import DeckParts
from ygo_kito.construction_layer_flow import _restriction_match, _wire_native_summon_dag_and_gates
from ygo_kito.construction_relations import (
    InputGroup,
    Need,
    RelationContext,
    RelationFact,
    Resource,
    UseRequirement,
    evaluate_relations,
    relation_index,
)
from ygo_kito.native_registrations import _read_summon_stock
from tests.test_construction_layers import skeleton


class _ListHandle:
    def __init__(self, lines):
        self._iter = iter(lines)

    def __iter__(self):
        return self._iter

    def __next__(self):
        return next(self._iter)

    def readline(self):
        try:
            return next(self._iter)
        except StopIteration:
            return ""


def _monster_row(cid, *, lv=4, ctype=0x21, rank=0, atk=1500, name=None):
    return {
        "id": cid,
        "alias": 0,
        "ot": 1,
        "type": ctype,
        "level": rank or lv,
        "race": 1,
        "attribute": 1,
        "atk": atk,
        "def": 0,
        "setcode": 0,
        "name": name or f"card-{cid}",
        "desc": "",
    }


def _monster_rule(cid, sec="main", *, cannot_ns=False, lv=4, rank=0, inherent_ss_procs=()):
    return {
        "card_id": cid,
        "section": sec,
        "cannot_normal_summon": cannot_ns,
        "nomi_restricted": False,
        "revive_limit": sec == "extra",
        "level": lv,
        "rank": rank,
        "link_rating": 0,
        "is_tuner": False,
        "is_flip": False,
        "is_pendulum": False,
        "pendulum_level": 0,
        "markers": 0,
        "downward_arrows": 0,
        "lscale": 0,
        "rscale": 0,
        "inherent_ss_procs": list(inherent_ss_procs),
    }


def _eval_summon_dag(main, extra, rows, stock, payoff_uses, *, extra_facts=(), ritual_proofs=None, op_facts=None):
    available = DeckParts(main=tuple(main), extra=tuple(extra), side=())
    dependencies = SimpleNamespace(
        native_summon_stock={(tuple(available.main), tuple(available.extra)): stock},
        rows=rows,
    )
    records = {c: [] for c in set(main) | set(extra)}
    rel_facts = list(extra_facts)
    rel_pools = {}
    rel_uses = list(payoff_uses)
    operation_facts = dict(op_facts or {})
    static_facts_meta = []
    effect_ready_facts = {}
    fusion_proofs = {}
    r_proofs = dict(ritual_proofs or {})
    _wire_native_summon_dag_and_gates(
        available, records, set(extra), dependencies, {},
        rel_facts, rel_pools, rel_uses, operation_facts,
        static_facts_meta, effect_ready_facts, fusion_proofs, r_proofs,
    )
    ctx = RelationContext(tuple(rel_uses), tuple(rel_facts), tuple(rel_pools.values()))
    index = relation_index(None, ctx)
    counts = Counter((z, c) for z in ("main", "extra") for c in getattr(available, z))
    return evaluate_relations(skeleton(tuple(main), tuple(extra)), ctx, index, inventory_counts=counts).data


class ConstructionSummonScoringTests(unittest.TestCase):
    def test_read_summon_stock_parses_with_own_ok_legacy_and_ritual_incomplete(self):
        main = [65367484, 549481, 301, 302, 303, 304, 305, 306]
        extra = [21044178]
        lines = [
            # copy_s, cannot_ns, nomi, revive_limit, lv, rank, lnk, is_tuner, is_flip, is_pend, pend_lv, markers, down, ls, rs
            "monster_rule\t1\t1\t1\t0\t4\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\n",
            "monster_rule\t2\t0\t0\t0\t4\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\n",
            "monster_rule\t9\t1\t0\t1\t0\t4\t0\t0\t0\t0\t0\t0\t0\t0\t0\n",
            # 6-col empty-field only (with_own_ok=0)
            "inherent_ss\t1\t0\t2000\t1\t0\t0\n",
            # 6-col opp-field SS requiring empty own MZONE (with_own_ok=0)
            "inherent_ss\t1\t1\t2000\t0\t1\t0\n",
            # Legacy 5-col backwards compatible (defaults holds_with_own_monster=True, requires_empty_own_mzone=False)
            "inherent_ss\t3\t0\t2000\t1\t0\n",
            "monster_rule\t3\t0\t0\t0\t4\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\n",
            # Ritual with 5 material copies and an incomplete ritual target
            "ritual\t0\t4\t5,6,7,8,3\n",
            "ritual_incomplete\t1\t4\tsearch_budget_exhausted\n",
            "end\n",
        ]
        stock = _read_summon_stock(
            _ListHandle(lines), main, extra, {},
            ritual_requests={"req_ok": (300, 0, 0), "req_unk": (300, 1, 0)},
        )
        procs_thrasher = stock["monster_rules"][65367484]["inherent_ss_procs"]
        self.assertEqual(len(procs_thrasher), 2)
        self.assertTrue(all(p["requires_empty_own_mzone"] and not p["holds_with_own_monster"] for p in procs_thrasher))
        procs_legacy = stock["monster_rules"][301]["inherent_ss_procs"]
        self.assertEqual(len(procs_legacy), 1)
        self.assertTrue(procs_legacy[0]["holds_with_own_monster"])
        self.assertFalse(procs_legacy[0]["requires_empty_own_mzone"])

        self.assertEqual(stock["ritual"]["req_ok"]["status"], "inventory_present")
        self.assertEqual(len(stock["ritual"]["req_ok"]["options"][0]["materials"]), 5)
        self.assertEqual(stock["ritual"]["req_unk"]["status"], "unknown")
        self.assertEqual(stock["ritual"]["req_unk"]["uncovered_targets"], [302])
        self.assertEqual(stock["ritual"]["req_unk"]["incomplete_reasons"], {302: "search_budget_exhausted"})

    def test_empty_own_mzone_and_ns_pool_three_controls_and_multi_mat_ordering(self):
        rows = {
            101: _monster_row(101, name="empty-ss-1"),
            102: _monster_row(102, name="empty-ss-2"),
            103: _monster_row(103, ctype=0x11, name="ns-only-1"),
            104: _monster_row(104, ctype=0x11, name="ns-only-2"),
            105: _monster_row(105, name="anytime-ss"),
            201: _monster_row(201, lv=0, rank=4, ctype=0x800021, name="rank4-xyz"),
        }
        empty_proc = [{"proc_index": 0, "range": 2, "holds_empty_board": True,
                       "holds_with_opponent_monster": False, "holds_with_own_monster": False,
                       "requires_empty_own_mzone": True}]
        base_rules = {
            101: _monster_rule(101, cannot_ns=True, inherent_ss_procs=empty_proc),
            102: _monster_rule(102, cannot_ns=True, inherent_ss_procs=empty_proc),
            103: _monster_rule(103, cannot_ns=False),
            104: _monster_rule(104, cannot_ns=False),
            105: _monster_rule(105, cannot_ns=True, inherent_ss_procs=[{
                "proc_index": 0, "range": 2, "holds_empty_board": True,
                "holds_with_opponent_monster": False, "holds_with_own_monster": True,
                "requires_empty_own_mzone": False,
            }]),
            201: _monster_rule(201, sec="extra", cannot_ns=True, lv=0, rank=4),
        }
        payoff = UseRequirement(
            "use:xyz",
            InputGroup("all", (Need("need:xyz", Resource("field_entry", attributes=("card:201",)), mode="presence"),)),
            "summon rank4",
            required=False,
        )

        # Control 1: 2x empty-field-only SS -> missing (EMPTY_OWN_MZONE_POOL capacity=1)
        res_two_empty = _eval_summon_dag(
            [101, 102], [201], rows,
            {"monster_rules": base_rules, "xyz": [{"target": 201, "target_copy": 3, "proc_index": 0,
                "is_alternate_overlay": False, "requires_external_state": None, "attached_count": 2,
                "materials": [{"card_id": 101, "section": "main"}, {"card_id": 102, "section": "main"}]}]},
            [payoff],
        )
        self.assertEqual(res_two_empty["uses"]["use:xyz"]["status"], "missing")

        # Control 2: 1x empty-field SS + 1x NS-only -> supported
        res_empty_plus_ns = _eval_summon_dag(
            [101, 103], [201], rows,
            {"monster_rules": base_rules, "xyz": [{"target": 201, "target_copy": 3, "proc_index": 0,
                "is_alternate_overlay": False, "requires_external_state": None, "attached_count": 2,
                "materials": [{"card_id": 101, "section": "main"}, {"card_id": 103, "section": "main"}]}]},
            [payoff],
        )
        self.assertEqual(res_empty_plus_ns["uses"]["use:xyz"]["status"], "supported")

        # Control 3: 2x NS-only -> missing (NS_POOL capacity=1)
        res_two_ns = _eval_summon_dag(
            [103, 104], [201], rows,
            {"monster_rules": base_rules, "xyz": [{"target": 201, "target_copy": 3, "proc_index": 0,
                "is_alternate_overlay": False, "requires_external_state": None, "attached_count": 2,
                "materials": [{"card_id": 103, "section": "main"}, {"card_id": 104, "section": "main"}]}]},
            [payoff],
        )
        self.assertEqual(res_two_ns["uses"]["use:xyz"]["status"], "missing")

        # Multi-material option ordering: unusable (103, 104) comes BEFORE usable (101, 103)
        res_ordered = _eval_summon_dag(
            [101, 103, 104, 105], [201], rows,
            {"monster_rules": base_rules, "xyz": [
                {"target": 201, "target_copy": 5, "proc_index": 0, "is_alternate_overlay": False,
                 "requires_external_state": None, "attached_count": 2,
                 "materials": [{"card_id": 103, "section": "main"}, {"card_id": 104, "section": "main"}]},
                {"target": 201, "target_copy": 5, "proc_index": 0, "is_alternate_overlay": False,
                 "requires_external_state": None, "attached_count": 2,
                 "materials": [{"card_id": 101, "section": "main"}, {"card_id": 103, "section": "main"}]},
            ]},
            [payoff],
        )
        self.assertEqual(res_ordered["uses"]["use:xyz"]["status"], "supported")

    def test_ritual_incomplete_propagates_unknown_and_complete_succeeds(self):
        rows = {
            300: {"id": 300, "alias": 0, "ot": 1, "type": 0x82, "level": 0, "name": "ritual-spell", "desc": ""},
            301: _monster_row(301, lv=8, ctype=0x81, name="ritual-mon"),
        }
        rules = {301: _monster_rule(301, cannot_ns=True, lv=8)}
        op_fact = RelationFact("op:rit", "op:rit", Resource("functional_operation", attributes=("op:rit",)),
                               "spell", 300, "main")
        payoff = UseRequirement(
            "use:rit",
            InputGroup("all", (Need("need:rit", Resource("field_entry", attributes=("card:301",)), mode="presence"),)),
            "ritual summon",
            required=False,
        )
        assign_fact = RelationFact(
            "op:rit:assign", "op:rit:assign",
            Resource("ritual_assignment", attributes=("op:rit", "target:301")),
            "ritual_recipe", 300, "main",
        )
        res_ok = _eval_summon_dag(
            [300, 301], [], rows, {"monster_rules": rules}, [payoff],
            extra_facts=[op_fact, assign_fact],
            op_facts={(300, 0, 0): "functional:op:rit"},
            ritual_proofs={(300, 0, 0): {
                "status": "inventory_present",
                "options": [{"target": 301, "materials": []}],
                "uncovered_targets": [],
                "target_resource_kinds": {301: "ritual_assignment"},
            }},
        )
        self.assertEqual(res_ok["uses"]["use:rit"]["status"], "supported")

        # Budget-exhausted incomplete ritual -> unknown (never silently missing!)
        res_unk = _eval_summon_dag(
            [300, 301], [], rows, {"monster_rules": rules}, [payoff],
            extra_facts=[op_fact],
            op_facts={(300, 0, 0): "functional:op:rit"},
            ritual_proofs={(300, 0, 0): {
                "status": "unknown",
                "options": [],
                "uncovered_targets": [301],
                "incomplete_reasons": {301: "search_budget_exhausted"},
            }},
        )
        self.assertEqual(res_unk["uses"]["use:rit"]["status"], "unknown")
        self.assertIn("ritual_material_search_incomplete", res_unk["uses"]["use:rit"]["unknown"])

    def test_zeus_battle_precondition_and_inherited_material_conflict(self):
        rows = {
            101: _monster_row(101, name="empty-ss"),
            103: _monster_row(103, ctype=0x11, name="ns-lv4"),
            201: _monster_row(201, lv=0, rank=4, ctype=0x800021, name="rank4-xyz"),
            90448279: _monster_row(90448279, lv=0, rank=12, ctype=0x800021, name="zeus"),
        }
        empty_proc = [{"proc_index": 0, "range": 2, "holds_empty_board": True,
                       "holds_with_opponent_monster": False, "holds_with_own_monster": False,
                       "requires_empty_own_mzone": True}]
        rules = {
            101: _monster_rule(101, cannot_ns=True, inherent_ss_procs=empty_proc),
            103: _monster_rule(103, cannot_ns=False),
            201: _monster_rule(201, sec="extra", cannot_ns=True, lv=0, rank=4),
            90448279: _monster_rule(90448279, sec="extra", cannot_ns=True, lv=0, rank=12),
        }
        stock = {
            "monster_rules": rules,
            "xyz": [
                {"target": 201, "target_copy": 3, "proc_index": 0, "is_alternate_overlay": False,
                 "requires_external_state": None, "attached_count": 2,
                 "materials": [{"card_id": 101, "section": "main"}, {"card_id": 103, "section": "main"}]},
                {"target": 90448279, "target_copy": 4, "proc_index": 1, "is_alternate_overlay": True,
                 "requires_external_state": "battle_phase_xyz_battled", "attached_count": 1,
                 "materials": [{"card_id": 201, "section": "extra"}]},
            ],
        }
        zeus_detach_2 = UseRequirement(
            "use:zeus:wipe",
            InputGroup("all", (
                Need("z:fe", Resource("field_entry", attributes=("card:90448279",)), mode="presence"),
                Need("z:mat", Resource("xyz_materials", attributes=("card:90448279",)), quantity=2, mode="consume"),
            )),
            "zeus effect detach 2",
            required=True,
        )
        zeus_detach_1 = UseRequirement(
            "use:zeus:one",
            InputGroup("all", (
                Need("z1:fe", Resource("field_entry", attributes=("card:90448279",)), mode="presence"),
                Need("z1:mat", Resource("xyz_materials", attributes=("card:90448279",)), quantity=1, mode="consume"),
            )),
            "zeus effect detach 1 (own overlay body only)",
            required=True,
        )
        base_detach_2 = UseRequirement(
            "use:base:detach2",
            InputGroup("all", (Need("b:mat", Resource("xyz_materials", attributes=("card:201",)), quantity=2, mode="consume"),)),
            "base xyz detach 2",
            required=True,
        )

        # Standalone Zeus detach-2 structurally supported AND propagates battle_phase_xyz_battled condition
        res_solo = _eval_summon_dag([101, 103], [201, 90448279], rows, stock, [zeus_detach_2])
        self.assertEqual(res_solo["uses"]["use:zeus:wipe"]["status"], "supported")
        self.assertEqual(res_solo["joint_required"]["status"], "supported")
        self.assertIn("battle_phase_xyz_battled", res_solo["uses"]["use:zeus:wipe"]["conditions"])

        # Joint consumption: if base XYZ consumes both its attached materials, Zeus cannot inherit 1 (conflicts)
        res_conflict = _eval_summon_dag([101, 103], [201, 90448279], rows, stock, [base_detach_2, zeus_detach_2])
        self.assertEqual(res_conflict["uses"]["use:base:detach2"]["status"], "supported")
        self.assertEqual(res_conflict["uses"]["use:zeus:wipe"]["status"], "supported")
        self.assertEqual(res_conflict["joint_required"]["status"], "missing")

        # However Zeus detaching only 1 (its own 201 body overlay without inheriting base's spent materials) stays jointly feasible!
        res_no_conflict = _eval_summon_dag([101, 103], [201, 90448279], rows, stock, [base_detach_2, zeus_detach_1])
        self.assertEqual(res_no_conflict["joint_required"]["status"], "supported")

        # Alternate-overlay option selection must prioritize base Xyz with attached materials over unsummonable low-ID Xyzs
        extra_rows = dict(rows)
        extra_rules = dict(rules)
        for low_id in (10, 11, 12):
            extra_rows[low_id] = _monster_row(low_id, lv=0, rank=4, ctype=0x800021, name=f"unsummonable-xyz-{low_id}")
            extra_rules[low_id] = _monster_rule(low_id, sec="extra", cannot_ns=True, lv=0, rank=4)
        extra_stock = {
            "monster_rules": extra_rules,
            "xyz": [
                *stock["xyz"],
                *(
                    {
                        "target": 90448279, "target_copy": 4, "proc_index": 1, "is_alternate_overlay": True,
                        "requires_external_state": "battle_phase_xyz_battled", "attached_count": 1,
                        "materials": [{"card_id": low_id, "section": "extra"}],
                    }
                    for low_id in (10, 11, 12)
                ),
            ],
        }
        res_prio = _eval_summon_dag([101, 103], [10, 11, 12, 201, 90448279], extra_rows, extra_stock, [zeus_detach_2])
        self.assertEqual(res_prio["uses"]["use:zeus:wipe"]["status"], "supported")

    def test_extra_sourced_ess_and_pendulum_excluded_from_pre_extra_entry_priority(self):
        # Extra Link 900 emits a circular dag:ess:900:... floating entry for NS-only card 101.
        # _wire_native_summon_dag_and_gates must ignore Extra-sourced dag:ess when ranking Link options,
        # so it selects [101 (NS), 202 (empty SS)] rather than circular [101, 101].
        rows = {
            101: _monster_row(101, ctype=0x11, name="ns-only"),
            202: _monster_row(202, name="empty-ss"),
            900: _monster_row(900, lv=0, ctype=0x4000021, name="extra-link"),
        }
        empty_proc = [{"proc_index": 0, "range": 2, "holds_empty_board": True,
                       "holds_with_opponent_monster": False, "holds_with_own_monster": False,
                       "requires_empty_own_mzone": True}]
        rules = {
            101: _monster_rule(101, cannot_ns=False),
            202: _monster_rule(202, cannot_ns=True, inherent_ss_procs=empty_proc),
            900: {**_monster_rule(900, sec="extra", cannot_ns=True, lv=0), "link_rating": 2, "link_markers": 5, "downward_arrows": 2},
        }
        stock = {
            "monster_rules": rules,
            "link": [
                {"target": 900, "target_copy": 3, "proc_index": 0, "link_rating": 2, "link_markers": 5,
                 "downward_arrows": 2, "materials": [{"card_id": 101, "section": "main"}, {"card_id": 101, "section": "main"}]},
                {"target": 900, "target_copy": 3, "proc_index": 0, "link_rating": 2, "link_markers": 5,
                 "downward_arrows": 2, "materials": [{"card_id": 101, "section": "main"}, {"card_id": 202, "section": "main"}]},
            ],
        }
        link_op_fact = RelationFact(
            "dag:ess:900:0:0:0:101:0", "dag:ess:900:0:0:0:101:0",
            Resource("field_entry", attributes=("card:101", "slot:0", "summon:special", "proper:yes", "pre_scale:yes")),
            "effect_special_summon", 101, "main",
            inputs=InputGroup("all", (Need("circ:src", Resource("field_entry", attributes=("card:900", "summon:special")), mode="presence"),)),
        )
        payoff = UseRequirement(
            "use:link900",
            InputGroup("all", (Need("l:fe", Resource("field_entry", attributes=("card:900", "summon:special")), mode="presence"),)),
            "extra link payoff",
            required=True,
        )
        res = _eval_summon_dag([101, 101, 202], [900], rows, stock, [payoff], extra_facts=[link_op_fact])
        self.assertEqual(res["uses"]["use:link900"]["status"], "supported")

    def test_restriction_match_skips_resource_only_costs(self):
        lock_rule = {
            "kind": "cannot_special_summon",
            "scope": "player",
            "controller": "self",
            "owner": "self",
            "allowed_summons": {"field": "setcode", "value": 175},
        }
        detail = {
            "card_id": 197042,
            "semantics": {"kind": "special_summon", "from_zones": ["grave"], "owner": "self", "controller": "self"},
            "operation": {"phase": "resolution", "controller": "self"},
            "costs": [{"resource": "lp", "quantity": 800, "reason": "cost", "owner": "self"}],
            "trigger": {"zone": "spell"},
            "summoned_card_ids": [197042],
        }
        card_props = {"197042": {"id": 197042, "type": 0x4, "setcode": 0}}
        # Must not crash on {'resource': 'lp'} cost; and should detect non-archetype SS restriction cleanly
        self.assertTrue(_restriction_match(lock_rule, detail, card_props))


if __name__ == "__main__":
    unittest.main()
