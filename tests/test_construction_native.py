import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import digest
from ygo_kito.validation import ContractError

from ygo_kito.construction_native import (
    NativeRuleChecks,
    _bind_movement,
    _choice_tokens,
    _field_moves,
    _resolved_deck_moves,
    planned_queries,
)
from ygo_kito.construction_native_evidence import chain_links


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

    def test_grave_arrival_requires_the_native_special_summon_completion(self):
        activation = dict(link=1, player=0)
        move = dict(kind=50, player=0, from_zone=16, to_zone=4, public_card=2, reason=0x800)
        summon = dict(kind=62, player=0, public_summoning_card=2)
        selected = {("graveyard", 2)}
        self.assertFalse(_field_moves(activation, [move, summon], selected, 0))
        settled = _field_moves(activation, [move, summon, {"kind": 63}], selected, 0)
        self.assertEqual([(m["kind"], m["card"]) for m in settled], [("special_summon", 2)])
