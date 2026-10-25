import copy
import json
from pathlib import Path
import unittest

from ygo_kito.build_contracts import BuildTask
from ygo_kito.catalog_search import CatalogQuery
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


class DiscoveryContractsTests(unittest.TestCase):
    def test_v3_extra_goal_without_route_retains_all_other_hard_constraints(self):
        raw = json.loads((ROOT / "configs/build-extra-discovery-v3.json").read_text())
        task = BuildTask.from_dict(raw)
        self.assertNotIn("route", task.goal)
        self.assertEqual(task, BuildTask.from_dict(task.to_dict()))
        for mutate in (lambda d: d.update(schema_version=2),
                       lambda d: d["goal"].update(route=[]),
                       lambda d: d["goal"]["starting_conditions"].update(seed=7),
                       lambda d: d["requirements"].__setitem__(0, dict(d["requirements"][0], minimum=0))):
            bad = copy.deepcopy(raw)
            mutate(bad)
            with self.assertRaises(ContractError):
                BuildTask.from_dict(bad)

    def test_catalog_query_requires_bounded_public_search_evidence(self):
        good = CatalogQuery.from_dict({"effect_terms": ["特殊召唤"], "theme_terms": ["银河"], "context_terms": ["调整"]})
        self.assertEqual(good.theme_terms, ("银河",))
        for raw in ({}, {"effect_terms": ["a"] * 9}, {"context_terms": ["x" * 65]},
                    {"preferred_level": True}, {"preferred_type": 0}, {"theme_terms": ["x"], "opponent_hand": [123]}):
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                CatalogQuery.from_dict(raw)
