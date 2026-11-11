"""Official-text partial observations: contract tests, not engine/role validation."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from ygo_kito.multifactor import FactorContractError, Factors
from ygo_kito.multifactor.semantics import group_from_semantics

FIXTURE = Path(__file__).parent / "fixtures" / "multifactor-real-effect-observations-v1.json"


class MultifactorRealEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.samples = {row["key"]: row for row in payload["samples"]}

    def group(self, key):
        row = self.samples[key]
        return group_from_semantics(row["snapshot"], key=key, source_ref=row["official_source"], confidence=1, uncertainty=0)

    def test_ash_response_conditions_are_not_its_search_or_summon_effects(self):
        group = self.group("ash-blossom")
        self.assertEqual(group.factors.get("effect_negate").value, 1)
        self.assertEqual(group.factors.get("effect_once_per_turn").value, 1)
        for name in ("effect_search", "effect_special_summon", "effect_send_grave", "activation_access", "one_card_independence"):
            self.assertIsNone(group.factors.get(name).value, name)
        self.assertTrue(any("costs=" in note and "cost" in note for note in group.notes))

    def test_desires_payment_is_not_resolution_and_piece_risk_stays_unknown(self):
        group = self.group("pot-of-desires")
        self.assertEqual(group.factors.get("effect_draw").value, 1)
        for name in ("effect_send_grave", "resource_cost", "resource_return", "required_brick_fraction", "cross_context_utility"):
            self.assertIsNone(group.factors.get(name).value, name)
        self.assertTrue(any("face_down" in note and "10" in note for note in group.notes))

    def test_branded_scoped_player_lock_is_not_global_compatibility_verdict(self):
        group = self.group("branded-fusion")
        self.assertEqual(group.factors.get("effect_fusion").value, 1)
        self.assertEqual(group.factors.get("effect_player_lock").value, 1)
        for name in ("summon_lock_risk", "goal_contribution", "activation_access", "external_dependency"):
            self.assertIsNone(group.factors.get(name).value, name)
        self.assertTrue(any("whole_turn" in note and "extra_fusion_only" in note for note in group.notes))

    def test_official_examples_have_no_role_labels_full_digest_or_period_approval(self):
        for key, sample in self.samples.items():
            self.assertTrue(sample["official_source"].startswith("https://www.db.yugioh-card.com/yugiohdb/card_search.action?"))
            self.assertNotIn("roles", sample)
            self.assertIsNone(sample["snapshot"]["text_sha256"])
            group = self.group(key)
            self.assertTrue(all("text_digest_unknown" in obs.source for _, obs in group.factors.items))
            self.assertTrue(any("no OCG-period or engine certification" in note for note in group.notes))

    def test_version_unknown_operations_and_costs_do_not_become_effects(self):
        original = self.samples["ash-blossom"]
        snapshot = deepcopy(original["snapshot"])
        snapshot["semantic_version"] = "unseen-schema"
        with self.assertRaises(FactorContractError):
            group_from_semantics(snapshot, key="anything", source_ref=original["official_source"])
        snapshot = deepcopy(original["snapshot"])
        snapshot["effects"][0]["operations"].extend([
            dict(kind="search_or_recover", reason="effect", from_zones=["deck", "grave"], source="ambiguous origins"),
            dict(kind="send_grave", reason="cost", source="payment is not resolution"),
            dict(kind="unrecognized_operation", reason="effect", source="unknown operation"),
        ])
        group = group_from_semantics(snapshot, key="anything", source_ref=original["official_source"])
        self.assertIsNone(group.factors.get("effect_search").value)
        self.assertIsNone(group.factors.get("effect_recover").value)
        self.assertIsNone(group.factors.get("effect_send_grave").value)
        self.assertTrue(any("unsupported_operation" in note for note in group.notes))

    def test_host_measurements_are_explicit_and_semantic_reliability_defaults_are_unclaimed(self):
        row = self.samples["branded-fusion"]
        measured = Factors.observed("group", {"activation_access": 0.6}, source="artificial host measurement; no engine run")
        group = group_from_semantics(row["snapshot"], key="package", source_ref=row["official_source"], measured=measured)
        self.assertEqual(group.factors.get("activation_access").value, 0.6)
        self.assertEqual(group.factors.get("effect_fusion").confidence, 0)
        self.assertEqual(group.factors.get("effect_fusion").uncertainty, 1)
        with self.assertRaisesRegex(FactorContractError, "overwrite"):
            group_from_semantics(row["snapshot"], key="package", source_ref=row["official_source"],
                                 measured=Factors.observed("group", {"effect_fusion": 0}, source="conflicting host assertion"))

    def test_current_card_rows_propose_typed_targets_without_a_seed(self):
        from ygo_kito.multifactor.contracts import AnalysisContext, DeckSpec, RoleInput
        from ygo_kito.multifactor.semantics import build_analysis_graph

        rows = {
            1: dict(id=1, type=2, desc='①：从手卡·卡组把1只3星以下的念动力族怪兽特殊召唤。这个效果特殊召唤的怪兽在这个回合的结束阶段除外。'),
            2: dict(id=2, type=33, race=1048576, level=3, desc=''),
            3: dict(id=3, type=33, race=1048576, level=4, desc=''),
            4: dict(id=4, type=2, desc='①：支付1000基本分才能发动。把1只5星以下的融合怪兽当作融合召唤从额外卡组特殊召唤。'),
            5: dict(id=5, type=97, race=1048576, level=2, desc=''),
            6: dict(id=6, type=97, level=8, desc=''),
            7: dict(id=7, type=2, desc='①：从卡组把2只3星以下的念动力族怪兽特殊召唤。'),
            8: dict(id=8, type=33, race=1048576, level=1, desc=''),
        }
        rows = {code: dict(row, name='anonymous '+str(code)) for code, row in rows.items()}
        example = RoleInput('catalog observation', Factors('context'), (), analysis_mode='deck_analysis', analysis_context=AnalysisContext(),
            deck=DeckSpec(((1, 1), (2, 1), (3, 1), (4, 1), (7, 1), (8, 1)), ((5, 1), (6, 1)), ()))
        result = build_analysis_graph(example, card_rows=rows)
        candidates = {(frozenset(v.members), v.functions) for v in result.candidates.candidates}
        def contains(*values, function):
            return (frozenset((f'card:{code}', 1) for code in values), (function,)) in candidates
        self.assertTrue(contains(1, 2, function='special_summon'))
        self.assertFalse(contains(1, 3, function='special_summon'))
        self.assertFalse(contains(1, 5, function='special_summon'))
        self.assertTrue(contains(4, 5, function='fusion_summon'))
        self.assertFalse(contains(4, 6, function='fusion_summon'))
        self.assertTrue(contains(7, 2, 8, function='special_summon'))
        self.assertFalse(contains(7, 2, function='special_summon'))

    def test_offline_review_keeps_explicit_negative_and_scoped_compatibility(self):
        from training.axis_generic.full18_sources import contrast_evidence, reviewed_contrast_records
        from ygo_kito.multifactor.contracts import RoleInput

        text = '从手卡·卡组把1只3星以下的念动力族怪兽特殊召唤'
        rows = {1: dict(id=1, name='spell', type=2, desc='①：'+text+'。'),
                2: dict(id=2, name='lower level', type=33, race=1048576, level=3, desc=''),
                3: dict(id=3, name='higher level', type=33, race=1048576, level=4, desc='')}
        review = dict(mechanism_contrasts=[dict(card_id=1, focus='special_summon', quote=text,
            coordinates=dict(special_summon=1, target=0), basis='printed resolution selection')],
            receiver_contrasts=[dict(id='psychic', card_id=1, focus='special_summon', quote=text, check='target',
                                    section='main', eligible=2, ineligible=3)])
        mechanisms, receivers = contrast_evidence(review, rows)
        case = dict(case_id='original-deck', main=[[1, 1], [2, 1]], extra=[])
        mechanism, present, absent = reviewed_contrast_records(case, rows, mechanisms, receivers)
        cells = mechanism['targets']['task_labels'][0]['cells']
        self.assertEqual(cells['target']['value'], 0)
        self.assertNotIn('draw', cells)
        span, = mechanism['provenance']['source_coordinates']
        self.assertEqual(rows[1]['desc'][span['start']:span['end']], text)
        for row, expected in ((present, 'compatible'), (absent, 'conflict')):
            self.assertEqual(row['targets']['task_labels'][0]['cells']['compatibility']['value'], expected)
            self.assertNotIn('function_seeds', row['observations'])
            self.assertEqual(row['provenance']['parent_id'], 'legacy-case:original-deck')
            self.assertFalse(row['provenance']['final_eval_eligible'])
        self.assertIn(2, dict(RoleInput.from_dict(present['observations']['input']).deck.main))
        self.assertNotIn(2, dict(RoleInput.from_dict(absent['observations']['input']).deck.main))


if __name__ == "__main__":
    unittest.main()
