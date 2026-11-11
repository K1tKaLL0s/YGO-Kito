"""First-layer behavior on anonymous inventories, without Torch or CB execution."""

from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.construction_logic import ConstructionLogic, LogicNode, LogicTag
from ygo_kito.construction_layers import (
    AxisModule, CardCopy, FunctionEvidence, FunctionRequirement, LayerContext,
    RoleAssessment, SkeletonSpec, evaluate_axis,
)
from ygo_kito.validation import ContractError


def task():
    raw = json.loads((Path(__file__).resolve().parents[1] / "configs/build-engineering-v1.json").read_text(encoding="utf-8"))
    raw.update(task_id="anonymous-axis-test", pool=list(range(1, 121)),
               sizes={"main": 40, "extra": 15, "side": 15},
               requirements=[{"zone": "main", "card_id": 1, "minimum": 1, "maximum": 3}])
    raw["goal"]["card_id"] = 1
    raw["goal"]["starting_conditions"]["requires_opening_hand"] = [1]
    return BuildTask.from_dict(raw)


def refs(code, count=1, zone="main"):
    return tuple(CardCopy(zone, code, i) for i in range(1, count + 1))


def requirement(name="entry", zone="main", **kwargs):
    return FunctionRequirement(name, zone, "explicit synthetic task/logic", (name,), **kwargs)


def evidence(name="entry", status="covered", **kwargs):
    return FunctionEvidence(name, status, "synthetic reviewed fact", **kwargs)


def role(code, functions=("entry",), q=1, module="axis", zone="main"):
    return RoleAssessment(module, zone, code, q, "synthetic role review",
                          tuple(evidence(f) for f in functions))


def context(requirements=None, assessments=(), *, extra_nodes=(), **kwargs):
    requirements = (requirement(),) if requirements is None else requirements
    names = sorted({n for r in requirements for n in r.node_ids} | set(extra_nodes)) or ["task"]
    nodes = tuple(LogicNode(n, (LogicTag("effect", n),)) for n in names)
    logic = ConstructionLogic("anonymous-logic", nodes, (), tuple(names), tuple(names))
    return LayerContext(task(), logic, requirements, assessments, **kwargs)


def skeleton(main=(), extra=(), side=(), *, modules=None, **kwargs):
    inventory = DeckParts(tuple(main), tuple(extra), tuple(side))
    if modules is None:
        cards = tuple(c for c in SkeletonSpec(inventory, ()).copies() if c.zone != "side")
        modules = (AxisModule("axis", "explicit task function", cards),)
    return SkeletonSpec(inventory, modules, **kwargs)


class AxisEvaluationTests(unittest.TestCase):
    def test_main_and_extra_marginal_discounts_and_undiscounted_direction(self):
        for n, main_e, extra_e in ((1, 1, 1), (2, 1.9, 1.8), (3, 2.8, 2.6)):
            with self.subTest(n=n):
                result = evaluate_axis(skeleton([1] * n, [2] * n), context(
                    (requirement(), requirement("target", "extra", mode="target")),
                    (role(1), role(2, ("target",), zone="extra"))))
                row = result["overview"]["functions"]["entry"]
                self.assertEqual((row["K"], row["E"]), (n, main_e))
                self.assertAlmostEqual(row["axis_density"], main_e / n)
                self.assertAlmostEqual(row["deck_density"], main_e / 40)
                self.assertEqual(result["overview"]["partitions"]["main"]["A"]["value"], 1)
                self.assertAlmostEqual(result["overview"]["partitions"]["extra"]["U"]["value"], extra_e / n)

    def test_shared_modules_and_split_copies_use_one_ledger(self):
        modules = (AxisModule("a", "first copy", refs(1)),
                   AxisModule("b", "later copies", refs(1, 3)[1:]),
                   AxisModule("c", "shared references", refs(1, 3)))
        result = evaluate_axis(skeleton([1] * 3, modules=modules), context(
            assessments=tuple(role(1, module=m.module_id) for m in modules)))
        self.assertEqual(result["slots"]["main"]["allocated"], 3)
        self.assertEqual(result["modules"]["a"]["functions"]["entry"]["E"], 1)
        self.assertEqual(result["modules"]["b"]["functions"]["entry"]["E"], 1.8)
        self.assertEqual(result["modules"]["c"]["functions"]["entry"]["E"], 2.8)
        self.assertEqual(result["overview"]["functions"]["entry"]["E"], 2.8)

    def test_shared_extra_and_function_views_never_add_card_slots(self):
        modules = tuple(AxisModule(m, "same target", refs(2, 3, "extra"), ("extra",)) for m in ("a", "b"))
        result = evaluate_axis(skeleton(extra=[2] * 3, modules=modules), context(
            (requirement("target", "extra"), requirement("supply", "extra")),
            tuple(role(2, ("target", "supply"), module=m, zone="extra") for m in ("a", "b"))))
        self.assertEqual(result["slots"]["extra"]["allocated"], 3)
        self.assertAlmostEqual(result["overview"]["partitions"]["extra"]["U"]["value"], 2.6 / 3)
        self.assertIsNone(result["overview"]["functions"]["supply"]["E"])

    def test_side_and_unassigned_extra_do_not_cover_axis(self):
        result = evaluate_axis(skeleton([1], [2], [3] * 3,
            modules=(AxisModule("axis", "main only", refs(1)),)), context(
            (requirement(), requirement("target", "extra")), (role(1, ()),)))
        self.assertEqual(result["overview"]["functions"]["entry"]["status"], "missing")
        self.assertEqual(result["overview"]["functions"]["target"]["status"], "missing")
        self.assertEqual(result["slots"]["side"]["status"], "deferred")
        self.assertEqual(result["slots"]["extra"]["unassigned"], 1)
        with self.assertRaises(ContractError):
            AxisModule("bad", "side cannot fill main", refs(3, 3, "side"))

    def test_unknown_and_mismatch_are_distinct_and_local(self):
        ctx = context((requirement(), requirement("supply"), requirement("interaction")), (
            role(1), role(2, (), q=0), role(3, (), q=.5),
            RoleAssessment("axis", "main", 4, 1, "partly reviewed", (evidence("supply", "unknown"),)),
            role(5, (), q=None)))
        # The unknown role explicitly rules out the other functions, so only
        # its supply remains unknown; an omitted role would affect all functions.
        ctx = replace(ctx, assessments=ctx.assessments[:-1] + (replace(ctx.assessments[-1], functions=(
            evidence("entry", "missing"), evidence("interaction", "missing"), evidence("supply", "unknown"))),))
        out = evaluate_axis(skeleton([1, 2, 3, 4, 5]), ctx)["overview"]
        self.assertEqual(out["functions"]["entry"]["status"], "covered")
        self.assertEqual(out["functions"]["supply"]["status"], "unknown")
        self.assertEqual(out["functions"]["interaction"]["status"], "missing")
        self.assertIsNone(out["partitions"]["main"]["A"]["value"])
        self.assertEqual(out["partitions"]["main"]["A"]["known_numerator"], 2.5)
        self.assertEqual(out["functions"]["supply"]["E"], 0)
        self.assertEqual(out["functions"]["supply"]["quantity_status"], "partial")

    def test_half_role_never_covers_core_and_mismatch_stays_in_denominator(self):
        out = evaluate_axis(skeleton([1, 2, 3]), context(assessments=(
            role(1), role(2, (), q=.5), role(3, (), q=0))))["overview"]
        self.assertEqual(out["partitions"]["main"]["A"]["value"], .5)
        self.assertEqual(out["functions"]["entry"]["K"], 1)
        self.assertAlmostEqual(out["functions"]["entry"]["axis_density"], 1 / 3)
        with self.assertRaises(ContractError):
            role(2, q=.5)

    def test_unknown_extra_u_is_not_zero_and_known_support_resolves_shared_role(self):
        shared = tuple(AxisModule(m, "target", refs(2, zone="extra"), ("extra",)) for m in ("a", "b"))
        ctx = context((requirement("target", "extra"),), (role(2, (), q=None, module="a", zone="extra"),))
        out = evaluate_axis(skeleton(extra=[2], modules=shared), ctx)
        self.assertIsNone(out["overview"]["partitions"]["extra"]["U"]["value"])
        ctx = replace(ctx, assessments=ctx.assessments + (role(2, ("target",), module="b", zone="extra"),))
        out = evaluate_axis(skeleton(extra=[2], modules=shared), ctx)
        self.assertEqual(out["overview"]["partitions"]["extra"]["U"]["value"], 1)
        self.assertEqual(out["overview"]["functions"]["target"]["unknown_copies"], [])

    def test_empty_required_partition_and_no_extra_target(self):
        out = evaluate_axis(skeleton(), context())["overview"]
        self.assertEqual(out["partitions"]["main"]["A"]["value"], 0)
        self.assertEqual(out["partitions"]["extra"]["U"]["status"], "not_applicable")
        required = evaluate_axis(skeleton(), context((requirement("target", "extra"),)))["overview"]
        self.assertEqual(required["partitions"]["extra"]["U"]["value"], 0)
        self.assertIn({"kind": "empty_required_partition", "zone": "extra"}, required["gaps"])

    def test_unassigned_and_vacant_purposes_are_preserved(self):
        purposes = {CardCopy("main", 2): "pending generic selection"}
        skel = skeleton([1, 2], modules=(AxisModule("axis", "core", refs(1)),),
                        unassigned_purposes=purposes, vacancy_purposes={"main": "pending completion"})
        purposes[CardCopy("main", 2)] = "caller mutation"
        result = evaluate_axis(skel, context(assessments=(role(1),)))
        main = result["slots"]["main"]
        self.assertEqual((main["budget"], main["allocated"], main["unassigned"], main["vacant"]), (40, 1, 1, 38))
        self.assertEqual(main["unassigned_copies"][0]["purpose"], "pending generic selection")
        self.assertEqual(main["vacancy_purpose"], "pending completion")
        self.assertFalse(result["inventory_complete"])

    def test_pure_axis_unselected_module_has_no_penalty_or_bonus(self):
        skel = skeleton([1])
        ctx = context(assessments=(role(1),))
        before = evaluate_axis(skel, ctx)
        skel = replace(skel, modules=skel.modules + (AxisModule("unused", "optional", selected=False),))
        after = evaluate_axis(skel, ctx)
        self.assertEqual(before["overview"], after["overview"])
        self.assertEqual(after["modules"]["unused"]["status"], "not_adopted")

    def test_preparation_nodes_need_statistics_or_given_input(self):
        ctx = context(assessments=(role(1),), extra_nodes=("prepare",))
        out = evaluate_axis(skeleton([1]), ctx)
        self.assertEqual([g["node_id"] for g in out["logic_gaps"]], ["prepare"])
        ctx = replace(ctx, requirements=ctx.requirements + (requirement("prepare", given_input="task gives this resource"),))
        out = evaluate_axis(skeleton([1]), ctx)
        self.assertEqual(out["logic_gaps"], [])
        self.assertEqual(out["overview"]["functions"]["prepare"]["status"], "given_input")
        self.assertIsNone(out["overview"]["functions"]["prepare"]["E"])

    def test_removing_a_copy_increases_density_but_decreases_investment(self):
        ctx = context(assessments=(role(1),))
        rows = [evaluate_axis(skeleton([1] * n), ctx)["overview"]["functions"]["entry"] for n in (3, 2)]
        self.assertGreater(rows[0]["E"], rows[1]["E"])
        self.assertLess(rows[0]["axis_density"], rows[1]["axis_density"])
        self.assertGreater(rows[0]["deck_density"], rows[1]["deck_density"])
        self.assertEqual([r["deck_denominator"] for r in rows], [40, 40])

    def test_unassigned_or_unsupported_copy_cannot_consume_function_first_copy(self):
        only_second = AxisModule("axis", "selected copy", (CardCopy("main", 1, 2),))
        ctx = context(assessments=(role(1),))
        out = evaluate_axis(skeleton([1, 1], modules=(only_second,)), ctx)
        self.assertEqual(out["overview"]["functions"]["entry"]["E"], 1)
        unsupported_first = AxisModule("other", "no entry role", refs(1))
        ctx = replace(ctx, assessments=ctx.assessments + (role(1, (), module="other"),))
        out = evaluate_axis(skeleton([1, 1], modules=(only_second, unsupported_first)), ctx)
        self.assertEqual(out["overview"]["functions"]["entry"]["E"], 1)
        self.assertEqual(out["overview"]["functions"]["entry"]["axis_denominator"], 2)

    def test_specific_supply_functions_and_conditions_do_not_collapse_or_multiply_yield(self):
        names = ("deck_random_effect", "deck_targeted_effect", "hand_effect", "field_effect", "hand_cost")
        ctx = context(tuple(requirement(n) for n in names), tuple(
            replace(role(i, (n,)), functions=(evidence(n, conditions=("after event",),
                effect_refs=(f"synthetic:{i}:effect:1",), per_resolution=5 if i == 1 else 3),))
            for i, n in enumerate(names, 1)))
        out = evaluate_axis(skeleton([1, 1, 1, 2, 3, 4, 5]), ctx)["overview"]["functions"]
        self.assertEqual(out[names[0]]["E"], 2.8)
        self.assertEqual([out[n]["E"] for n in names[1:]], [1, 1, 1, 1])
        self.assertEqual(out[names[0]]["evidence"][0]["per_resolution"], 5)
        self.assertEqual(out[names[0]]["evidence"][0]["conditions"], ("after event",))

    def test_targeted_tool_is_not_counted_as_independent_entry(self):
        out = evaluate_axis(skeleton([1]), context((requirement("tool", mode="target"),),
            (role(1, ("tool",)),)))["overview"]["functions"]["tool"]
        self.assertEqual((out["status"], out["K"]), ("covered", 1))
        self.assertIsNone(out["E"])
        self.assertIsNone(out["deck_density"])

    def test_duplicate_tags_effect_evidence_and_enumeration_do_not_add_investment(self):
        assessment = replace(role(1), functions=(evidence(), evidence(), evidence(effect_refs=("second effect",))))
        ctx = context(assessments=(assessment, role(2)))
        a = evaluate_axis(skeleton([1, 1, 2]), ctx)
        b = evaluate_axis(skeleton([2, 1, 1]), replace(ctx, assessments=tuple(reversed(ctx.assessments))))
        self.assertEqual(a["overview"], b["overview"])
        self.assertEqual(a["overview"]["functions"]["entry"]["E"], 2.9)
        self.assertEqual(len(a["overview"]["functions"]["entry"]["evidence"]), 2)

    def test_same_name_aliases_share_count_and_discount(self):
        out = evaluate_axis(skeleton([1, 2, 2]), context(assessments=(role(1), role(2)),
            same_name_groups=((1, 2),)))
        self.assertEqual(out["overview"]["functions"]["entry"]["E"], 2.8)
        with self.assertRaises(ContractError):
            evaluate_axis(skeleton([1, 1, 2], side=[2]), context(same_name_groups=((1, 2),)))

    def test_anonymous_multimodule_totals_match_fixed_r31_acceptance_values(self):
        # Fixed acceptance quantities from r3.1; IDs are arbitrary, never a recipe.
        functions = {"entry": {2, 3, 4, 5, 10}, "convert": {1, 3, 4},
                     "random": {1, 3, 4, 7, 11, 12}, "targeted": {2, 8},
                     "hand": {2, 3, 9}, "field": {6, 10}}
        layouts = (
            ({1: 3, 2: 3, 3: 3, 4: 1, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},
             {11: 3, 12: 3, 13: 2, 14: 2}, {15: 1, 16: 1, 17: 1}, {60: 2, 61: 1, 62: 1}),
            ({2: 3, 3: 3, 4: 1, 6: 3, 7: 3, 8: 2, 9: 3, 10: 3}, {}, {}, {60: 3, 61: 3, 62: 3}),
        )
        outputs = []
        for primary, aux, other, extra in layouts:
            groups = {"axis": primary, "aux": aux, "other": other}
            modules, assessments, main = [], [], []
            for name, counts in groups.items():
                cards = tuple(c for code, n in counts.items() for c in refs(code, n))
                main.extend(c.card_id for c in cards)
                if name == "axis":
                    cards += tuple(c for code, n in extra.items() for c in refs(code, n, "extra"))
                modules.append(AxisModule(name, "anonymous selected module", cards, selected=bool(cards)))
                assessments.extend(role(code, tuple(f for f, codes in functions.items() if code in codes), module=name)
                                   for code in counts)
            assessments.extend(role(code, (), zone="extra") for code in extra)
            main.extend(range(80, 80 + 40 - len(main)))
            outputs.append(evaluate_axis(skeleton(main, [c for c, n in extra.items() for _ in range(n)],
                modules=tuple(modules)), context(tuple(requirement(f) for f in functions), tuple(assessments))))
        for out, expected in zip(outputs, ((18, 31, 6.6, 7.6, 13.2, .95), (21, 21, 3.8, 6.6, 6.6, 2.6 / 3))):
            axis_n, total_n, convert_e, random_e, total_random_e, u = expected
            axis = out["modules"]["axis"]
            overview = out["overview"]
            self.assertEqual(axis["functions"]["entry"]["E"], 9.4)
            self.assertEqual(axis["functions"]["convert"]["E"], convert_e)
            self.assertEqual(axis["functions"]["random"]["E"], random_e)
            self.assertEqual(overview["functions"]["random"]["E"], total_random_e)
            self.assertEqual(axis["functions"]["random"]["axis_denominator"], axis_n)
            self.assertEqual(overview["functions"]["random"]["axis_denominator"], total_n)
            self.assertAlmostEqual(overview["functions"]["random"]["deck_density"], total_random_e / 40)
            self.assertAlmostEqual(axis["partitions"]["extra"]["U"]["value"], u)

    def test_card_and_module_renaming_preserves_numeric_results(self):
        baseline = evaluate_axis(skeleton([1, 1, 2]), context(assessments=(role(1), role(2))))
        changed = evaluate_axis(skeleton([31, 31, 32], modules=(
            AxisModule("renamed", "same purpose", refs(31, 2) + refs(32)),)), context(
                assessments=(role(31, module="renamed"), role(32, module="renamed"))))
        for result in (baseline, changed):
            row = result["overview"]["functions"]["entry"]
            self.assertEqual((row["K"], row["E"], row["deck_denominator"]), (3, 2.9, 40))
            self.assertEqual(result["overview"]["partitions"]["main"]["A"]["value"], 1)

    def test_contracts_reject_bad_counts_stale_candidate_references_and_sources(self):
        failures = (
            lambda: CardCopy("main", 1, True), lambda: CardCopy("main", 1, 0),
            lambda: skeleton([1] * 4), lambda: AxisModule("a", "purpose", refs(1) * 2),
            lambda: skeleton([1], modules=(AxisModule("axis", "absent copy", refs(1, 2)),)),
            lambda: evaluate_axis(skeleton([1, 1], side=[1, 1]), context()),
            lambda: evaluate_axis(skeleton([1]), context(assessments=(role(2),))),
            lambda: role(1, q=True), lambda: replace(evidence(), source=""),
            lambda: evaluate_axis(skeleton([1]), context((requirement(module_ids=("absent",)),))),
            lambda: replace(context(), requirements=(requirement(), requirement())),
            lambda: replace(context(), assessments=(role(1), role(1))),
            lambda: evaluate_axis(skeleton([1]), context(assessments=(role(1, ("absent",)),))),
            lambda: skeleton([1], unassigned_purposes={CardCopy("main", 1): "cannot hide core"}),
        )
        for index, fail in enumerate(failures):
            with self.subTest(case=index), self.assertRaises(ContractError):
                fail()

    def test_original_task_budgets_and_pool_are_preserved(self):
        for skel in (skeleton(list(range(1, 42))), skeleton([121])):
            with self.assertRaises(ContractError):
                evaluate_axis(skel, context())
        ctx = context()
        out = evaluate_axis(skeleton(), ctx)
        self.assertEqual(out["task"], ctx.task.to_dict())
        self.assertEqual(out["task_requirement_gaps"][0]["present"], 0)
        out["task"]["sizes"]["main"] = 1
        self.assertEqual(ctx.task.sizes["main"], 40)

    def test_no_cb_native_model_or_training_execution(self):
        # The kernel has no model/engine dependency. Trap native construction
        # already imported by the legacy DTO, and reject optional heavy imports.
        import builtins
        original_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name.split(".")[0] == "torch" or any(x in name for x in ("basic_cb", "build_training", "scenario_course")):
                raise AssertionError("forbidden execution dependency: " + name)
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded), patch(
                "ctypes.CDLL", side_effect=AssertionError("native execution forbidden")):
            result = evaluate_axis(skeleton([1]), context(assessments=(role(1),)))
        self.assertEqual(result["layer"], "axis")
        self.assertNotIn("score", result)
        self.assertNotIn("cb_verified", result)
        json.dumps(result, allow_nan=False)


class AdapterTests(unittest.TestCase):
    @staticmethod
    def assets():
        from ygo_kito.build_pipeline import BuildAssets
        from ygo_kito.effect_mechanisms import MechanismCatalog
        data = task().to_dict()
        data["sizes"] = {"main": 40, "extra": 0, "side": 0}
        data["candidate_budget"] = 32
        original = BuildTask.from_dict(data)
        assets = BuildAssets.__new__(BuildAssets)
        assets.environment, assets.limits = original.environment, {}
        assets.rows = {c: {"id": c, "alias": 0, "ot": 1, "type": 17, "race": 1, "setcode": 0,
            "level": 4, "attribute": 1, "atk": 1000, "def": 1000,
            "name": f"anonymous-{c}", "desc": ""} for c in original.pool}
        assets.receipt = {"resources": {"cards": "anonymous-catalog-source"}}
        return original, assets, MechanismCatalog(assets)

    def test_catalog_cost_target_not_removed_by_route_ready(self):
        from ygo_kito.construction_relations import RelationContext, relation_index
        _, assets, catalog = self.assets()
        assets.rows[1]["desc"] = "①：丢弃1张手卡，以自己场上1只怪兽为对象才能发动。从自己卡组上面把3张卡送去墓地。"
        self.assertFalse(catalog.card(1).effects[0].route_ready)
        index = relation_index(catalog, RelationContext((), catalog_cards=(1,)))
        facts = list(index.facts.values())
        self.assertTrue(facts)
        self.assertEqual(facts[0].output.kind, "mill")
        kinds = {n.resource.kind for n in facts[0].inputs.items}
        self.assertTrue({"payment", "target"} <= kinds)
        self.assertTrue(index.observations[1]["records"][0]["costs"])
        self.assertEqual(facts[0].quantity, 3)
        self.assertEqual(facts[0].unknown, ())

    def test_real_record_import_can_use_sourced_activation_and_stays_effect_scoped(self):
        from ygo_kito.construction_relations import (
            InputGroup, Need, RelationContext, RelationFact, Resource, UseRequirement, relation_index,
        )
        from ygo_kito.construction_layers import evaluate_layers
        original, assets, catalog = self.assets()
        assets.rows[1]["desc"] = "这个卡名的①的效果1回合只能使用1次。①：自己主要阶段才能发动。从自己卡组上面把3张卡送去墓地。"
        activate = RelationFact("given", "task-input", Resource("activation", zone="field", reason="not_applicable",
            event="own_main_phase", attributes=("card:1",)), "explicit task phase and access")
        ctx = replace(context(requirements=()), task=original, relations=RelationContext((
            UseRequirement("supply", InputGroup("all", (Need("mill", Resource("mill", "grave", "deck", "effect", "sent_to_grave", "random"), 3),)), "task"),),
            facts=(activate,), catalog_cards=(1,)))
        output = evaluate_layers(skeleton((1,)), ctx, catalog)
        self.assertEqual(output["relations"]["uses"]["supply"]["status"], "supported")
        self.assertEqual(output["validation"], "partial_inventory")
        self.assertIn("catalog-limit:1:1", output["relations"]["uses"]["supply"]["bottlenecks"])
        index = relation_index(catalog, ctx)
        self.assertEqual(index.counters["catalog_cache_hits"], 1)
        assets.rows[1]["desc"] = "①：自己主要阶段才能发动。抽1张。"
        from ygo_kito.construction_relations import evaluate_relations
        with self.assertRaises(ContractError):
            evaluate_relations(skeleton((1,)), ctx, index)
        fresh = relation_index(catalog, ctx)
        self.assertNotEqual(index.observations[1]["text_sha256"], fresh.observations[1]["text_sha256"])
        self.assertFalse(any(f.output.kind == "mill" for f in fresh.facts.values()))

    def test_materials_are_explicit_all_inputs_without_automatic_summon(self):
        from ygo_kito.construction_relations import RelationContext, relation_index
        _, assets, catalog = self.assets()
        assets.rows[2].update(type=0x41, desc="「anonymous-1」＋战士族怪兽\n①：自己主要阶段才能发动。抽1张。")
        index = relation_index(catalog, RelationContext((), catalog_cards=(2,)))
        material = index.facts["catalog:2:materials"]
        self.assertEqual(material.zone, "extra")
        self.assertEqual(material.inputs.operator, "all")
        self.assertEqual(len(material.inputs.items), 2)
        self.assertEqual(material.output.kind, "material_ready")
        self.assertTrue(index.observations[2]["materials"])

    def test_unknown_catalog_operation_does_not_become_known_supply(self):
        from ygo_kito.construction_relations import RelationContext, UseRequirement, InputGroup, Need, Resource
        from ygo_kito.construction_layers import evaluate_layers
        _, assets, catalog = self.assets()
        assets.rows[1]["desc"] = "①：自己主要阶段才能发动。抽若干张。未知处理。"
        ctx = context(requirements=(), relations=RelationContext((
            UseRequirement("draw", InputGroup("all", (Need("wanted", Resource("draw")),)), "task"),), catalog_cards=(1,)))
        output = evaluate_layers(skeleton((1,)), ctx, catalog)
        self.assertEqual(output["relations"]["uses"]["draw"]["status"], "unknown")
        self.assertTrue(output["relations"]["observations"][1]["unknown"] or
                        output["relations"]["observations"][1]["records"][0]["unknown"])

    def test_full_list_reuses_assets_validate_and_keeps_hard_constraints(self):
        from ygo_kito.construction_relations import RelationContext
        from ygo_kito.construction_layers import evaluate_layers
        original, assets, catalog = self.assets()
        ctx = replace(context(requirements=(), relations=RelationContext(())), task=original)
        spec = skeleton(tuple(range(1, 41)))
        with patch.object(assets, "validate", wraps=assets.validate) as validator:
            output = evaluate_layers(spec, ctx, catalog)
            validator.assert_called_once_with(ctx.task, spec.inventory)
            self.assertEqual(output["validation"], "list_constraints_verified")
        assets.limits[1] = 0
        with self.assertRaises(ContractError):
            evaluate_layers(spec, ctx, catalog)
        with self.assertRaises(ContractError):
            evaluate_layers(spec, ctx)

    def test_existing_portfolio_rows_keep_identity_order_scores_and_own_skeleton(self):
        from ygo_kito.construction_candidates import portfolio
        from ygo_kito.construction_relations import RelationContext
        from ygo_kito.construction_layers import evaluate_portfolio_layers
        original, assets, catalog = self.assets()
        base = skeleton(tuple(range(1, 41)))
        other = skeleton(tuple(range(1, 40)) + (41,))
        rows = portfolio(original, assets, base=base.inventory, initial=(other.inventory,))
        for i, row in enumerate(rows):
            row["score"] = 2.5 - i
        specs = [skeleton(row["deck"].main) for row in rows]
        ctx = replace(context(requirements=(), relations=RelationContext(())), task=original)
        result = evaluate_portfolio_layers(rows, specs, ctx, catalog, generation_work={"examined": 400})
        self.assertEqual(result["upstream_generation_work"], {"examined": 400})
        for before, after in zip(rows, result["rows"]):
            for key, value in before.items():
                self.assertEqual(after[key], value)
        self.assertNotIn("layer_evaluation", rows[0])
        with self.assertRaises(ContractError):
            evaluate_portfolio_layers(rows, list(reversed(specs)), ctx, catalog)

    def test_candidate_budget_precedes_reads_and_handles_one_and_32(self):
        from ygo_kito.construction_relations import RelationContext, RelationBudget
        from ygo_kito.construction_layers import evaluate_portfolio_layers
        original, assets, catalog = self.assets()
        spec = skeleton(tuple(range(1, 41)))
        rows = [{"candidate_id": str(i), "deck": spec.inventory, "score": i} for i in range(40)]
        ctx = replace(context(requirements=()), task=original,
            relations=RelationContext((), catalog_cards=(1,), budget=RelationBudget(candidates=0)))
        with patch.object(catalog, "effect_records", wraps=catalog.effect_records) as read:
            self.assertEqual(evaluate_portfolio_layers(rows, [spec] * 40, ctx, catalog)["rows"], [])
            read.assert_not_called()
            for limit in (1, 32):
                bounded = replace(ctx, relations=replace(ctx.relations, budget=RelationBudget(candidates=limit)))
                result = evaluate_portfolio_layers(rows, [spec] * 40, bounded, catalog)
                self.assertEqual(len(result["rows"]), limit)
                self.assertEqual(result["budget"]["uncovered_positions"], list(range(limit, 40)))
            self.assertEqual(read.call_count, 2)

    def test_composition_never_imports_models_training_cb_or_loads_native(self):
        import builtins
        from ygo_kito.construction_relations import RelationContext
        from ygo_kito.construction_layers import evaluate_layers
        original_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            if any(v in name for v in ("torch", "basic_cb", "build_training", "build_model")):
                raise AssertionError("unexpected execution: " + name)
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded), patch("ctypes.CDLL", side_effect=AssertionError("native")):
            output = evaluate_layers(skeleton((1,)), context(requirements=(), relations=RelationContext(())))
            json.dumps(output, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
