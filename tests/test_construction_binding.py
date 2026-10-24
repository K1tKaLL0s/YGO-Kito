"""Catalog-backed CPU binding behavior; no native engine or training updates."""

from dataclasses import replace
import unittest
from unittest.mock import Mock

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_intent import classify_build_intent
from ygo_kito.construction_binding import (
    CardTagAssessment, CatalogBindingAdapter, PublicFactTag,
)
from ygo_kito.construction_fill import evaluate_fill, fill_with_existing
from ygo_kito.construction_logic import (
    ConstructionLogic, ConstructionSession, LogicConnector, LogicNode, LogicTag,
)
from ygo_kito.validation import ContractError
from tests.test_construction_logic import fixture_assets


def catalog():
    task, assets = fixture_assets()
    raw = task.to_dict()
    raw["schema_version"] = 4
    raw["goal"] = {"kind": "deck_constraints", "constraints": [{
        "id": "main-monsters", "zones": ["main"],
        "predicate": {"field": "type_all", "value": 17}, "minimum": 40, "maximum": 40}], "preferences": []}
    raw["environment"]["versions"]["card_pool"] = "native-private-knowledge-v5"
    task = BuildTask.from_dict(raw)
    assets.environment = task.environment
    assets.receipt = {"resources": {"cards": digest("synthetic-pinned-catalog")}}
    for row in assets.rows.values():
        row["desc"] = "Printed public description."
    assets.rows[1]["desc"] = "Send one card to the Graveyard."
    assets.rows[2]["desc"] = "Recover a card from the Graveyard."
    assets.rows[3]["setcode"] = 0x2123
    return task, assets


def one_node(tag):
    return ConstructionLogic("catalog-graph", (LogicNode("goal", (tag,)),), (), ("goal",), ("goal",))


def assessment(assets, code, tag, status="satisfied"):
    return CardTagAssessment(code, tag, status, assets.receipt["resources"]["cards"],
        digest(assets.rows[code]["desc"]), assets.rows[code]["desc"],
        "explicit-unit-assessment-not-real-card-semantics", "Source-bound assessment fixture.")


class CatalogBindingTests(unittest.TestCase):
    def setUp(self):
        self.task, self.assets = catalog()
        self.deck = DeckParts(tuple([1] * 3 + [2] * 3 + [3] * 3 + [4] * 3 +
                                    [c for c in range(5, 19) for _ in range(2)]))
        self.assets.validate(self.task, self.deck)

    def test_static_race_and_setcode_use_rows_instead_of_names_or_keywords(self):
        plant = LogicTag("race", "植物族")
        self.assets.rows[1]["name"] = "No race word appears here"
        self.assets.rows[5]["name"] = "植物族 is only a name string"
        adapter = CatalogBindingAdapter(self.assets)
        result = adapter.bind(one_node(plant), self.task, self.deck)
        self.assertEqual(result.status, "bound")
        self.assertLessEqual(result.proposal.bindings[0].card_ids[0], 4)
        chosen = result.proposal.bindings[0].card_ids[0]
        self.assertEqual(adapter.reviewer(one_node(plant).nodes[0], (self.assets.rows[chosen],)).status, "satisfied")
        theme = LogicTag("field", "未见字段")
        adapter = CatalogBindingAdapter(self.assets, fact_tags=(PublicFactTag(theme, "setcode", 0x2123, "explicit-schema-map"),))
        result = adapter.bind(one_node(theme), self.task, self.deck)
        self.assertEqual(result.status, "bound")
        self.assertEqual(result.proposal.bindings[0].card_ids, (3,))
        # Name text cannot supply missing subtype bits.
        self.assets.rows[1]["name"] = "未见字段"
        self.assertEqual(adapter.bind(one_node(theme), self.task, self.deck).proposal.bindings[0].card_ids, (3,))

    def test_functional_words_recall_cards_but_never_certify_effects(self):
        tag = LogicTag("effect", "送墓")
        graph = one_node(tag)
        adapter = CatalogBindingAdapter(self.assets, recall_terms={tag: ("Send", "Graveyard")})
        bound = adapter.bind(graph, self.task, self.deck)
        self.assertEqual(bound.status, "proposed_unknown")
        self.assertEqual(bound.proposal.bindings[0].card_ids, (1,))
        self.assertEqual(adapter.reviewer(graph.nodes[0], (self.assets.rows[1],)).status, "unknown")
        session = ConstructionSession("堆墓", self.task)
        session.classification = classify_build_intent("堆墓")  # Isolate binding from untrained intent weights.
        session.submit_logic(graph, role="user", reason="explicit abstract effect goal")
        verifier = Mock(side_effect=AssertionError("unknown card effect must not reach verification"))
        out = evaluate_fill(session, self.assets, bound.proposal, text_reviewer=adapter.reviewer, verifier=verifier)
        self.assertEqual(out["status"], "text_review_unknown")
        self.assertIsNone(out["best_deck"])
        verifier.assert_not_called()

    def test_explicit_assessment_binds_identity_text_and_catalog_source(self):
        tag = LogicTag("effect", "送墓")
        node = one_node(tag).nodes[0]
        good = assessment(self.assets, 1, tag)
        adapter = CatalogBindingAdapter(self.assets, assessments=(good,))
        self.assertEqual(adapter.bind(one_node(tag), self.task, self.deck).status, "bound")
        self.assertEqual(adapter.reviewer(node, (self.assets.rows[1],)).status, "satisfied")
        for record in (replace(good, cards_sha256="0" * 64), replace(good, effect_text_sha256="0" * 64),
                       replace(good, quote="not the printed text")):
            with self.subTest(record=record):
                stale = CatalogBindingAdapter(self.assets, assessments=(record,))
                self.assertEqual(stale.reviewer(node, (self.assets.rows[1],)).status, "unknown")
        self.assertEqual(adapter.reviewer(node, (self.assets.rows[2],)).status, "unknown")
        altered = dict(self.assets.rows[1], desc="caller supplied substitute text")
        self.assertEqual(adapter.reviewer(node, (altered,)).status, "unknown")

    def test_effect_type_is_not_inferred_from_monster_type_bits(self):
        tag = LogicTag("effect_type", "起动效果")
        with self.assertRaises(ContractError):
            PublicFactTag(tag, "type_all", 0x20, "unsupported-type-guess")
        graph = one_node(tag)
        self.assertEqual(CatalogBindingAdapter(self.assets).reviewer(graph.nodes[0], (self.assets.rows[1],)).status, "unknown")

    def test_negative_assessment_rejects_even_with_lexical_hits(self):
        tag = LogicTag("effect", "Send")
        adapter = CatalogBindingAdapter(self.assets, assessments=(assessment(self.assets, 1, tag, "unsatisfied"),))
        result = adapter.bind(one_node(tag), self.task, self.deck)
        self.assertEqual(result.status, "unmatched")
        self.assertIsNone(result.proposal)
        self.assertIn("goal", result.reasons[0])
        self.assertEqual(adapter.reviewer(one_node(tag).nodes[0], (self.assets.rows[1],)).status, "unsatisfied")
        with self.assertRaisesRegex(ContractError, "catalog binding unmatched.*goal"):
            adapter(one_node(tag), self.task, self.deck)

    def test_supported_alternative_path_precedes_lexical_unknown_and_merges(self):
        plant, send, recover = LogicTag("race", "植物族"), LogicTag("effect", "Send"), LogicTag("effect", "回收")
        graph = ConstructionLogic("branch", tuple(LogicNode(n, (tag,)) for n, tag in
            (("start", plant), ("unknown", send), ("reviewed", recover), ("finish", plant))),
            (LogicConnector("a", "start", "unknown", "ns"), LogicConnector("b", "unknown", "finish", "ss"),
             LogicConnector("z", "start", "reviewed", "ns"), LogicConnector("y", "reviewed", "finish", "送墓时发动")),
            ("start",), ("finish",))
        adapter = CatalogBindingAdapter(self.assets, assessments=(assessment(self.assets, 2, recover),))
        result = adapter.bind(graph, self.task, self.deck)
        self.assertEqual(result.status, "bound")
        self.assertEqual(set(result.proposal.connector_ids), {"z", "y"})
        self.assertEqual({b.node_id for b in result.proposal.bindings}, {"start", "reviewed", "finish"})
        self.assertFalse(result.to_dict().get("graph_execution_verified", False))

    def test_empty_text_and_required_list_constraints_do_not_fake_evidence(self):
        graph = one_node(LogicTag("effect", "Send"))
        adapter = CatalogBindingAdapter(self.assets)
        without = DeckParts(tuple(c for c in self.deck.main if c != 1) + (5, 6, 7))
        # Explicit task requirement still prevents replacing a required card.
        with self.assertRaises(ContractError):
            adapter.bind(graph, self.task, without)
        self.assets.rows[1]["desc"] = ""
        race = one_node(LogicTag("race", "植物族"))
        self.assertEqual(adapter.reviewer(race.nodes[0], (self.assets.rows[1],)).status, "unknown")

    def test_side_only_matches_and_disconnected_candidate_nodes_are_unmatched(self):
        adapter = CatalogBindingAdapter(self.assets)
        raw = self.task.to_dict()
        raw["sizes"]["side"] = 1
        task = BuildTask.from_dict(raw)
        main = tuple(c for c in self.deck.main if c != 18) + (5, 6)
        deck = DeckParts(main, (), (18,))
        self.assets.rows[18]["desc"] = "Side-exclusive effect text."
        self.assertEqual(adapter.bind(one_node(LogicTag("effect", "Side-exclusive")), task, deck).status, "unmatched")
        graph = ConstructionLogic("unmatched-path", (
            LogicNode("entry", (LogicTag("race", "植物族"),)),
            LogicNode("missing", (LogicTag("effect", "never-mentioned"),)),
            LogicNode("goal", (LogicTag("effect", "Send"),))),
            (LogicConnector("a", "entry", "missing", "ns"), LogicConnector("b", "missing", "goal", "ss")),
            ("entry",), ("goal",))
        result = adapter.bind(graph, self.task, self.deck)
        self.assertEqual(result.status, "unmatched")
        self.assertTrue(next(n for n in result.node_candidates if n["node_id"] == "goal")["candidates"])

    def test_strict_json_round_trip_and_duplicate_source_records_fail(self):
        tag = LogicTag("effect", "送墓")
        adapter = CatalogBindingAdapter(self.assets, assessments=(assessment(self.assets, 1, tag),),
                                        recall_terms={tag: ("Send",)})
        self.assertEqual(CatalogBindingAdapter.from_dict(self.assets, adapter.to_dict()).to_dict(), adapter.to_dict())
        for payload in ({"extra": 1}, {"fact_tags": {}}, {"assessments": "not an array"},
                        {"assessments": [dict(asmt, extra=True) for asmt in adapter.to_dict()["assessments"]]}):
            with self.subTest(payload=payload), self.assertRaises(ContractError):
                CatalogBindingAdapter.from_dict(self.assets, payload)
        record = assessment(self.assets, 1, tag)
        with self.assertRaises(ContractError):
            CatalogBindingAdapter(self.assets, assessments=(record, record))

    def test_actual_candidate_and_model_scoring_pipeline_uses_catalog_adapter(self):
        import torch
        from ygo_kito.build_model import BuildEncoder, BuildModelConfig, BuildRanker
        torch.set_num_threads(1)
        graph = one_node(LogicTag("race", "植物族"))
        session = ConstructionSession("堆墓", self.task)
        session.classification = classify_build_intent("堆墓")
        session.submit_logic(graph, role="user", reason="static tag integration")
        adapter = CatalogBindingAdapter(self.assets)
        config = BuildModelConfig()
        encoder = BuildEncoder(self.task, self.assets, config)
        models = {"build_optimizer": BuildRanker(config, len(self.task.pool), len(encoder.tags))}
        # Real existing candidate generator, Transformer forward, listing/count
        # checker, and this adapter; no provider fixture or engine response fake.
        out = fill_with_existing(session, self.assets, binding_provider=adapter, text_reviewer=adapter.reviewer,
                                 models=models, encoder=encoder, role="build_optimizer", base=self.deck)
        self.assertEqual(out["status"], "list_constraints_verified_logic_unproven")
        self.assertEqual(out["ranking"], "existing_role_model_uncalibrated")
        self.assertFalse(out["graph_execution_verified"])
        self.assertFalse(out["attempts"][0]["engine_validation"]["effect_execution_verified"])


if __name__ == "__main__":
    unittest.main()
