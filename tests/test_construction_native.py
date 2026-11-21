import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.build_pipeline import CatalogNativeEngine, MissingNativeScript
from ygo_kito.native import NativeError, NativeNormalEngine
from ygo_kito.validation import ContractError

from ygo_kito.construction_native import (
    NativeRuleChecks,
    _bind_movement,
    _choice_tokens,
    _field_moves,
    _resolved_deck_moves,
    _side_inventory,
    _summon_response_moves,
    planned_queries,
)
from ygo_kito.construction_native_evidence import chain_links, stock_prefix
from ygo_kito.effect_lua import LuaEffectSource


class ConstructionNativeTests(unittest.TestCase):
    def test_payment_and_resolution_stay_with_their_own_chain_link(self):
        opened = dict(kind=70, player=0, public_card=1, description=16, link=1)
        reply = dict(kind=70, player=1, public_card=2, description=32, link=2)
        paid = dict(kind=100, player=0, amount=1000, lp=7000)
        discarded = dict(kind=50, player=1, public_card=3, from_zone=2, to_zone=16, reason=0x80)
        events = [opened, paid, dict(kind=71, link=1), reply, discarded, dict(kind=71, link=2),
                  dict(kind=72, link=2), dict(kind=75, link=1), dict(kind=73, link=2),
                  dict(kind=74), opened, dict(kind=71, link=1), dict(kind=72, link=1), dict(kind=73, link=1)]
        first, response, later = chain_links(events)
        self.assertEqual(first['payments'], [dict(paid, event_index=1)])
        self.assertEqual(response['payments'], [dict(discarded, event_index=4)])
        self.assertEqual(response['response_to'], opened)
        self.assertFalse(first['resolved'])
        self.assertTrue(response['resolved'])
        self.assertTrue(later['resolved'])
        self.assertEqual(later['payments'], [])
        self.assertIsNone(later['response_to'])

    def test_movement_requires_selected_card_and_resolving_link(self):
        query = dict(card=1, seat=0, destinations=["hand", "grave"])
        activation = dict(kind=70, public_card=1, player=0, link=1, description=16)
        begin, end = dict(kind=72, link=1), dict(kind=73, link=1)
        hidden_hand = dict(kind=50, from_zone=1, to_zone=2, player=0, reason=64)
        moves = _resolved_deck_moves([activation, begin, hidden_hand, end], {2}, {2}, query, 16)
        self.assertEqual([(m["card"], m["destination"]) for m in moves], [(2, "hand")])
        self.assertFalse(_resolved_deck_moves([activation, begin, hidden_hand, end], {2}, set(), query, 16))
        self.assertFalse(_resolved_deck_moves([activation, hidden_hand, begin, end], {2}, {2}, query, 16))
        self.assertFalse(_resolved_deck_moves([activation, begin, hidden_hand, end, dict(kind=76, link=1)],
                                             {2}, {2}, query, 16))
        self.assertFalse(_resolved_deck_moves([activation, begin, hidden_hand, end], {2}, {2}, query, 17))

    def test_actual_registration_is_independent_of_printed_number(self):
        move = dict(card=2, destination="grave", activation={"description": 16})
        effect = dict(key="monster:2:1", trigger="unknown", scopes="monster", zone=None, spans=[],
                      operations=[dict(block="send", destination="grave", selector=None)])
        query = dict(setup="normal_summon", registrations=[
            dict(family=1, description=16, span=[3, 8], event="normal_summon")
        ], effects=[effect], wanted=[effect["key"]])
        self.assertEqual(_bind_movement(query, [move], {})["effect_key"], effect["key"])
        query["effects"].append(dict(effect, key="monster:3:2"))
        self.assertEqual(_bind_movement(query, [move], {})["status"], "printed_use_ambiguous")
        query["registrations"].append(dict(query["registrations"][0], family=2))
        self.assertEqual(_bind_movement(query, [move], {})["status"], "registration_ambiguous")

    def test_equivalent_physical_copies_share_one_branch(self):
        menu = [dict(action_id=str(i), kind="select", cards=[code], refs=[str(i)])
                for i, code in enumerate((3, 3, 4))]
        tokens = _choice_tokens(menu, 15, {"0", "1", "2"})
        self.assertEqual(tokens["0"], tokens["1"])
        self.assertNotEqual(tokens["0"], tokens["2"])

    def test_legal_alternatives_and_other_uses_share_the_budget(self):
        assets = SimpleNamespace(workspace=Path("."))
        checks = NativeRuleChecks(assets)
        queries = [dict(card=i, effects=[], wanted=["use"], setup="hand", path=[]) for i in (1, 2)]
        deck = SimpleNamespace(to_dict=lambda: dict(main=[1, 2]))
        task = SimpleNamespace(sha256="task")

        def ask(_task, _deck, query, _role, budget, _should_stop):
            self.assertEqual(budget, 100 if query["card"] == 1 else 50)
            return dict(receipt=str(query["card"]), status="settled", decisions=50,
                        alternatives=[dict(path=[["select", query["card"]]])])

        with patch.object(checks, "_ask", side_effect=ask):
            result = checks.evaluate(task, deck, role="candidate", queries=queries)
        self.assertEqual((result["eligible_cards"], result["known_windows"], result["decisions"]), (2, 4, 100))
        self.assertEqual(result["completed_windows"], 2)
        self.assertEqual([row["reason"] for row in result["pending"]], ["native_decision_budget"] * 2)

    def test_cached_receipt_requires_the_same_inventory_and_decision_limit(self):
        with TemporaryDirectory() as workspace:
            assets = SimpleNamespace(workspace=Path(workspace), receipt={"core": "pinned"},
                                     period_context={"period_id": "period"}, adapter_revision=5)
            task = SimpleNamespace(sha256="task")
            deck = SimpleNamespace(to_dict=lambda: dict(main=[1, 2]))
            changed_deck = SimpleNamespace(to_dict=lambda: dict(main=[1, 3]))
            query = dict(card=1, seat=0, path=[])
            fake_result = dict(status="not_offered", offered=False, decisions=5)
            with patch("ygo_kito.construction_native.run_window", return_value=fake_result) as run:
                cold = NativeRuleChecks(assets)._ask(task, deck, query, "candidate", 100, None)
                next_run = NativeRuleChecks(assets)
                self.assertEqual(next_run._ask(task, deck, query, "candidate", 100, None), cold)
                self.assertEqual(run.call_count, 1)
                self.assertNotEqual(next_run._ask(task, changed_deck, query, "candidate", 100, None), cold)
                self.assertNotEqual(next_run._ask(task, deck, query, "candidate", 90, None), cold)
                self.assertEqual(run.call_count, 3)
                self.assertEqual(next_run.counts["cache_hits"], 1)

    def test_missing_required_script_blocks_only_the_active_inventory_and_is_cached(self):
        with TemporaryDirectory() as workspace:
            lua = LuaEffectSource.__new__(LuaEffectSource)
            lua._scripts = {}
            lua._binding = {"scripts_sha256": "old"}
            assets = SimpleNamespace(workspace=Path(workspace), receipt={"scripts": "old"}, period_context={},
                adapter_revision=5, effect_lua_source=lua, rows={1: {"type": 0x11}, 2: {"type": 0x1000011}})
            task = SimpleNamespace(sha256="task")
            deck = DeckParts(main=(1,), side=(2,))
            checked = NativeRuleChecks(assets)
            query = dict(card=2, setup="hand", seat=0, path=[], summons=[], seed=7, opening=[],
                         side_swaps=[dict(zone="main", incoming=2, outgoing=1)])
            with patch("ygo_kito.construction_native.engine_for_goal", side_effect=OSError("engine")) as engine:
                expected = checked.evaluate(task, deck, role="reference", queries=[query])
                self.assertEqual(expected["status"], "missing_rule_source")
                receipt, = expected["receipts"]
                self.assertEqual(receipt["missing_scripts"], [dict(card_id=2, script_card_id=2,
                    file="c2.lua", scripts_sha256="old")])
                self.assertEqual(receipt["decisions"], 0)
                self.assertFalse(engine.called)
                cached = NativeRuleChecks(assets)
                self.assertEqual(cached._ask(task, deck, query, "reference", 100, None), receipt)
                self.assertEqual(cached.counts["cache_hits"], 1)
                resident = dict(query, card=1, side_swaps=[], opening=[1])
                self.assertEqual(cached._ask(task, deck, resident, "reference", 100, None)["status"], "engine_error")
                engine.assert_called_once()
                lua._scripts["c2.lua"] = (b"", "present")
                lua._binding = {"scripts_sha256": "new"}
                assets.receipt = {"scripts": "new"}
                self.assertEqual(cached._ask(task, deck, query, "reference", 100, None)["status"], "engine_error")
                self.assertEqual(engine.call_count, 2)

    def test_old_replay_rechecking_a_changed_script_keeps_both_receipts(self):
        with TemporaryDirectory() as workspace:
            assets = SimpleNamespace(workspace=Path(workspace), receipt={}, period_context={}, adapter_revision=5,
                                     native_code_overrides={}, rows={2: {"alias": 1}})
            task = SimpleNamespace(sha256="task")
            deck = SimpleNamespace(to_dict=lambda: dict(main=[3]))
            query = dict(card=3, seat=0, path=[])
            former = dict(status="not_offered", offered=False, decisions=1, scripts=["c1.lua"])
            checks = NativeRuleChecks(assets)
            with patch("ygo_kito.construction_native.run_window", return_value=former) as run:
                before = checks._ask(task, deck, query, "candidate", 100, None)
                assets.native_code_overrides = {2: (2, 1)}
                run.return_value = dict(former, scripts=["c2.lua"], native_code_projection=digest(assets.native_code_overrides))
                current = checks._ask(task, deck, query, "candidate", 100, None)
                self.assertNotEqual(current["receipt"], before["receipt"])
                self.assertTrue((checks.directory / (before["receipt"] + ".json")).is_file())
                self.assertEqual(checks._ask(task, deck, query, "candidate", 100, None), current)
                self.assertEqual(run.call_count, 2)

    def test_runtime_missing_helper_is_bound_to_the_window_and_resource_receipt(self):
        with TemporaryDirectory() as workspace:
            assets = SimpleNamespace(workspace=Path(workspace), period_context={}, adapter_revision=5,
                                     receipt={"resources": {"scripts": "original"}})
            task = SimpleNamespace(sha256="task")
            deck = DeckParts(main=(1,))
            query = dict(card=1, setup="hand", seat=0, path=[])

            def run(*args, counters, **kwargs):
                counters["submitted_decisions"] += 4
                raise MissingNativeScript(("common/missing.lua",))

            checker = NativeRuleChecks(assets)
            with patch("ygo_kito.construction_native.run_window", side_effect=run) as window:
                row = checker._ask(task, deck, query, "candidate", 100, None)
                self.assertEqual(row["status"], "missing_rule_source")
                self.assertEqual(row["decisions"], 4)
                self.assertEqual(row["missing_scripts"], [dict(file="common/missing.lua", scripts_sha256="original",
                                                              stage="execution")])
                self.assertEqual(checker._ask(task, deck, query, "candidate", 100, None), row)
                window.assert_called_once()
                assets.receipt = {"resources": {"scripts": "updated"}}
                window.side_effect = None
                window.return_value = dict(status="settled", decisions=4)
                ready = checker._ask(task, deck, query, "candidate", 100, None)
                self.assertEqual(ready["status"], "settled")
                self.assertNotEqual(ready["receipt"], row["receipt"])
                self.assertEqual(window.call_count, 2)

    def test_script_reader_attributes_only_paths_missing_from_the_snapshot(self):
        lua = LuaEffectSource.__new__(LuaEffectSource)
        lua._scripts = {"present.lua": (b"", "present")}
        engine = CatalogNativeEngine.__new__(CatalogNativeEngine)
        engine._catalog_assets = SimpleNamespace(effect_lua_source=lua, native_code_overrides={})
        engine._failed_scripts = set()
        engine._script_type = lambda callback: callback
        engine.lib = SimpleNamespace(set_script_reader=lambda callback: None)
        engine._callbacks = (lambda name, length: None, None, None)
        engine.callback_errors = ["script source missing or invalid"]
        with patch.object(NativeNormalEngine, "_install_callbacks"):
            engine._install_callbacks()
        script_reader = engine._callbacks[0]
        script_reader(b"./script/present.lua", None)
        script_reader(b"./script/../invalid.lua", None)
        with self.assertRaises(NativeError) as ordinary:
            engine._check_callbacks()
        self.assertNotIsInstance(ordinary.exception, MissingNativeScript)
        script_reader(b"./script/common/missing.lua", None)
        with self.assertRaises(MissingNativeScript) as missing:
            engine._check_callbacks()
        self.assertEqual(missing.exception.files, ("common/missing.lua",))

    def test_prior_windows_do_not_spend_the_resumed_budget(self):
        with TemporaryDirectory() as workspace:
            assets = SimpleNamespace(workspace=Path(workspace), receipt={"core": "pinned"},
                                     period_context={"period_id": "period"}, adapter_revision=5)
            task = SimpleNamespace(sha256="task")
            deck = SimpleNamespace(to_dict=lambda: dict(main=[1, 2, 3]))
            policy = {"policy": "original"}
            queries = [dict(card=i, setup="hand", seat=0, path=[]) for i in (1, 2, 3)]

            def run(_assets, _deck, query, *, decision_budget, **_options):
                needed = {1: 50, 2: 60, 3: 40}[query["card"]]
                return dict(status="settled" if decision_budget >= needed else "decision_budget",
                            decisions=min(needed, decision_budget))

            with patch("ygo_kito.construction_native.run_window", side_effect=run) as engine:
                prior = NativeRuleChecks(assets)
                baseline = prior.evaluate(task, deck, role="candidate", queries=queries)
                self.assertEqual(baseline["decisions"], 100)
                self.assertEqual([r["card"] for r in baseline["pending"]], [3])
                report = prior.report()
                report["inventories"][0]["admission"] = dict(policy=digest(policy), evaluation="prior",
                    effects=[dict(card=3, spans=[], facts=["required"], partial=False, hard=True, width=0.)])
                resumed = NativeRuleChecks(assets)
                resumed.load_frontier(report)
                engine.reset_mock()
                result = resumed.evaluate(task, deck, role="candidate", policy=policy)
                self.assertEqual([(call.args[2]["card"], call.kwargs["decision_budget"])
                                  for call in engine.call_args_list], [(3, 100), (2, 60)])
                self.assertEqual(result["status"], "complete")
                self.assertEqual(result["decisions"], 100)
                self.assertEqual(result["replayed_receipts"], report["inventories"][0]["receipts"])
                self.assertEqual(resumed.counts["frontier_replayed_decisions"], 100)
                self.assertEqual({r["query"]["card"] for r in result["receipts"]}, {1, 2, 3})

    def test_native_pause_serializes_remaining_budget_and_rejects_other_policy(self):
        with TemporaryDirectory() as workspace:
            assets = SimpleNamespace(workspace=Path(workspace), receipt={"core": "pinned"},
                                     period_context={"period_id": "period"}, adapter_revision=5)
            task = SimpleNamespace(sha256="task")
            deck = SimpleNamespace(to_dict=lambda: dict(main=[1, 2]))
            queries = [dict(card=i, setup="hand", seat=0, path=[]) for i in (1, 2)]
            paused = False

            def run(_assets, _deck, query, *, decision_budget, **_options):
                nonlocal paused
                if query["card"] == 1:
                    paused = True
                return dict(status="settled", decisions=min(25, decision_budget))

            checks = NativeRuleChecks(assets)
            with patch("ygo_kito.construction_native.run_window", side_effect=run) as engine:
                partial = checks.evaluate(task, deck, role="candidate", queries=queries, should_stop=lambda: paused)
                work = json.loads(json.dumps(partial["continuation"]))
                self.assertEqual(partial["decisions"], 25)
                restored = NativeRuleChecks(assets)
                with self.assertRaisesRegex(ContractError, "different inputs"):
                    restored.evaluate(task, deck, role="candidate", queries=queries, policy={"changed": True},
                                      continuation=work)
                result = restored.evaluate(task, deck, role="candidate", queries=queries, continuation=work)
                self.assertEqual([(call.args[2]["card"], call.kwargs["decision_budget"])
                                  for call in engine.call_args_list], [(1, 100), (2, 75)])
                self.assertEqual(result["decisions"], 50)
                self.assertEqual(result["receipts"][0], partial["receipts"][0])

    def test_same_stock_frontiers_keep_their_actual_admission_policy(self):
        checks = NativeRuleChecks(SimpleNamespace(workspace=Path("."), receipt={"core": "pinned"},
                                   period_context={"period_id": "period"}, adapter_revision=5))
        task = SimpleNamespace(sha256="task")
        deck = SimpleNamespace(to_dict=lambda: dict(main=[1, 2]))
        formal, frozen = {"theme": "formal"}, {"theme": "frozen"}
        prior = dict(task=task.sha256, deck=digest(deck.to_dict()), role="reference", status="decision_budget",
                     receipts=[], exhausted_receipts=[])
        checks.load_frontier(dict(version="construction-native-rules-v5", inventories=[
            dict(prior, policy=digest(policy), pending=[dict(query=dict(card=card, setup="hand", path=[]))])
            for card, policy in enumerate((formal, frozen), 1)]))

        def ask(_task, _deck, query, _role, _budget, _should_stop):
            return dict(receipt=str(query["card"]), status="settled", decisions=1, alternatives=[])

        with patch.object(checks, "_ask", side_effect=ask):
            work = checks.evaluate(task, deck, role="reference", policy=formal)
            locked = checks.evaluate(task, deck, role="reference", policy=frozen)
        self.assertNotEqual(work["frontier"], locked["frontier"])
        self.assertEqual([r["receipt"] for r in work["receipts"]], ["1"])
        self.assertEqual([r["receipt"] for r in locked["receipts"]], ["2"])

    def test_stock_still_gets_legal_windows_without_any_effect_records(self):
        deck = SimpleNamespace(main=(1, 1, 2))
        assets = SimpleNamespace(effect_lua_source=None, rows={
            1: dict(type=1, level=4),
            2: dict(type=2),
        })
        plans, excluded = planned_queries(deck, assets)
        self.assertFalse(excluded)
        self.assertEqual({(q["card"], q["setup"]) for q in plans},
                         {(1, "normal_summon"), (1, "hand"), (2, "spell")})
        self.assertTrue(all("effects" not in q for q in plans))

    def test_chain_activations_are_planned_from_settable_originals(self):
        registered = dict(type=16, event_code=1027, event=None, family=0, registration_span=[17, 29],
                          operation={"reference": "source"})
        lua = SimpleNamespace(summarize_effects=lambda code, **_options: {"script_card_id": code, "registrations":
            [registered] if code == 2 else [dict(registered, event_code=1002)]})
        assets = SimpleNamespace(effect_lua_source=lua, rows={10: dict(type=4, alias=2), 3: dict(type=4)})
        plans, excluded = planned_queries(SimpleNamespace(main=(10, 3), extra=(), side=()), assets)
        plan, = plans
        self.assertEqual((plan["card"], plan["setup"], plan["opening"], plan["prepare_set"]),
                         (10, "response", [10], True))
        self.assertEqual(excluded[0]["card"], 3)

    def test_hand_response_accepts_a_registered_range_that_includes_hand(self):
        source = dict(type=128, event_code=1027, family=0, registration_span=[17, 29],
                      operation={"reference": "source"})
        lua = SimpleNamespace(summarize_effects=lambda code: {"script_card_id": code, "registrations":
            [dict(source, range=2 | 4), dict(source, range=4, family=1, registration_span=[34, 39])]})
        assets = SimpleNamespace(effect_lua_source=lua, rows={1: dict(type=33, level=3)})
        plans, _ = planned_queries(DeckParts(main=(1,)), assets)
        response, = [q for q in plans if q["setup"] == "response" and not q.get("response_zone")]
        self.assertEqual(response["opening"], [1])
        self.assertEqual(response["response_to"], {"any_opponent_activation": True})
        self.assertNotIn("prepare_set", response)
        self.assertEqual([reg["family"] for reg in response["registrations"]], [0])
        field, = [q for q in plans if q.get("response_zone") == "monster"]
        self.assertEqual(field["summons"], [1])
        self.assertEqual([reg["family"] for reg in field["registrations"]], [0, 1])

    def test_side_windows_bind_physical_exchanges_and_resident_only_skips_them(self):
        deck = DeckParts((1, 2, 2), (), (3, 3))
        assets = SimpleNamespace(effect_lua_source=None, rows={c: dict(type=1, level=4) for c in (1, 2, 3)})
        plans, _ = planned_queries(deck, assets)
        side_plans = [q for q in plans if q.get("side_swaps")]
        self.assertEqual({q["card"] for q in side_plans}, {3})
        swap = side_plans[0]["side_swaps"]
        self.assertEqual(_side_inventory(deck, swap), DeckParts((3, 2, 2), (), (1, 3)))
        self.assertEqual(deck, DeckParts((1, 2, 2), (), (3, 3)))
        resident, _ = planned_queries(deck, assets, include_side=False)
        self.assertFalse(any(q.get("side_swaps") for q in resident))
        with self.assertRaisesRegex(ContractError, "actual side and active-deck copy"):
            _side_inventory(deck, swap + swap)

    def test_cards_with_a_shared_rule_name_load_their_own_registered_script(self):
        from ygo_kito.card_identity import native_card_identity, rule_name_id
        from ygo_kito.deck_profile import validate_deck_parts

        original = dict(alias=0, type=4, ot=1, name="Original", desc="Original effect")
        alternative = dict(original, alias=1, name="Different printing", desc="Different effect")
        artwork = dict(alternative, alias=2)
        rows = {1: original, 2: alternative, 3: artwork}
        self.assertEqual([native_card_identity(rows, c) for c in rows], [(1, 1), (2, 1), (2, 1)])
        fillers = list(range(4, 41))
        rows.update((c, dict(original)) for c in fillers)
        valid = dict(main=[1, 2, 3, *fillers], extra=[], side=[])
        validate_deck_parts(valid, rows, {})
        with self.assertRaisesRegex(ContractError, "combined main/extra/side alias limit"):
            validate_deck_parts(dict(valid, side=[3]), rows, {})
        self.assertEqual(rule_name_id(rows, 3), 1)

        lookup = []
        def summarize(code, **_options):
            lookup.append(code)
            return dict(registrations=[])
        assets = SimpleNamespace(effect_lua_source=SimpleNamespace(summarize_effects=summarize), rows=rows)
        planned_queries(SimpleNamespace(main=(1, 2, 3), extra=(), side=()), assets)
        self.assertEqual(lookup, [1, 2, 2])

    def test_masked_set_move_requires_a_matching_original_hand_entity(self):
        choice = dict(kind="set", refs=["p0.hand.0"], cards=[2])
        events = [dict(kind=90, player=0, count=1), dict(kind=11),
                  dict(kind=50, player=0, from_zone=2, to_zone=8), dict(kind=54),
                  dict(kind=70, public_card=2, player=0, zone=8)]
        query = dict(seat=0, opening=[2], summons=[], prepare_set=True)
        link = dict(activation=events[-1], turn=2, phase="main1", opened=4)
        step = (1, dict(seat=0, turn=1), choice)
        prefix = stock_prefix(events, [step], link, query, [], [])
        self.assertEqual(prefix["set_preparation"], dict(card=2, turn=1, activation_turn=2, zone="spell_trap"))
        self.assertIsNone(stock_prefix(events, [], link, query, [], []))
        self.assertIsNone(stock_prefix(events, [(1, step[1], dict(choice, cards=[3]))], link, query, [], []))
        self.assertIsNone(stock_prefix(events, [step], dict(link, turn=1), query, [], []))

    def test_summon_response_requires_the_pending_core_event_and_its_negation_callback(self):
        pending = dict(kind=62, public_summoning_card=2, player=1, zone=4, slot=0)
        activation = dict(kind=70, public_card=3, player=0, description=0)
        destroyed = dict(kind=50, public_card=2, player=1, from_zone=4, to_zone=16, reason=0x41)
        events = [pending, activation, dict(kind=72), destroyed, dict(kind=73)]
        link = dict(activation=activation, response_to=None, opened=1, solving=2, solved=4)
        registration = dict(description=0, direct_summon_negation=dict(attempts_destroy=True))
        query = dict(response_to=dict(summon_message=62), registrations=[registration])
        self.assertEqual([move["kind"] for move in _summon_response_moves(link, events, query)],
                         ["negate_summon", "destroy"])
        self.assertFalse(_summon_response_moves(link, [*events, dict(kind=63)], query))
        self.assertFalse(_summon_response_moves(link, events, dict(query, registrations=[{"description": 0}])))
        self.assertFalse(_summon_response_moves(link, events, dict(query, response_to={"summon_message": 60})))

    def test_grave_arrival_requires_the_native_special_summon_completion(self):
        activation = dict(link=1, player=0)
        move = dict(kind=50, player=0, from_zone=16, to_zone=4, public_card=2, reason=0x800)
        summon = dict(kind=62, player=0, public_summoning_card=2)
        selected = {("graveyard", 2)}
        self.assertFalse(_field_moves(activation, [move, summon], selected, 0))
        settled = _field_moves(activation, [move, summon, {"kind": 63}], selected, 0)
        self.assertEqual([(m["kind"], m["card"]) for m in settled], [("special_summon", 2)])
