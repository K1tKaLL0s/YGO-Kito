"""DP reference client to real construction RPC, with synthetic catalogue data.

These are local protocol/CPU composition checks, not a provider connection or
real card-effect/duel evidence. The only fit is the existing small synthetic
intent-classifier fixture. No graph/deck model training or native call is run.
"""

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ygo_kito.agent_bridge import AgentBridge
from ygo_kito.agent_driver import Client, LoopbackTransport, RemoteError
from ygo_kito.build_contracts import digest
from ygo_kito.build_pipeline import goal_candidates
from ygo_kito.construction_binding import CardTagAssessment
from ygo_kito.construction_logic import LogicTag
from ygo_kito.construction_service import ConstructionUnavailable, HostConstructionBackend
from ygo_kito.intent_model import LinearIntentClassifier
from ygo_kito.validation import ContractError
from tests.test_construction_logic import fixture_assets, fixture_classifier


class ConstructionServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.task, self.assets = fixture_assets()
        self.assets.receipt = {"resources": {"cards": "a" * 64}}
        self.tag = LogicTag("effect", "送墓")
        self.binding_data = {"assessments": [asdict(CardTagAssessment(
            code, self.tag, "satisfied", "a" * 64, digest(row["desc"]), "Synthetic card text",
            "explicit-synthetic-annotation", "Only checks local composition")) for code, row in self.assets.rows.items()]}
        self.backend = HostConstructionBackend(fixture_classifier(), assets=self.assets, binding_data=self.binding_data)
        self.request = {"request": "堆墓", "task": self.task.to_dict(), "required_tags": [asdict(self.tag)],
                        "base": goal_candidates(self.task, self.assets)[0].to_dict()}

    def client(self, role="manager", backend=None):
        bridge = AgentBridge(self.root, self.root / ("state-" + role), self.root / "missing-native",
                             role=role, construction_backend=backend)
        self.addCleanup(bridge.close)
        return Client(LoopbackTransport(bridge.dispatch))

    def test_dp_client_discovers_manager_methods_and_default_backend_is_closed(self):
        client = self.client()
        self.assertTrue(client.has("construction.plan"))
        self.assertTrue(client.has("construction.run"))
        self.assertFalse(client.capabilities()["construction_backend_configured"])
        for method, params in (("construction.plan", {"request": "堆墓"}), ("construction.run", self.request)):
            with self.subTest(method=method), self.assertRaises(RemoteError) as raised:
                client.call(method, params)
            self.assertEqual(raised.exception.code, "CONSTRUCTION_BACKEND_NOT_CONFIGURED")

    def test_only_fixed_manager_role_can_reach_construction(self):
        for role in ("monitor", "trainer", "opponent"):
            client = self.client(role, self.backend)
            self.assertFalse(client.has("construction.run"))
            for method in ("construction.plan", "construction.run"):
                with self.subTest(role=role, method=method), self.assertRaises(RemoteError) as raised:
                    client.call(method, self.request)
                self.assertEqual(raised.exception.code, "PERMISSION_DENIED")

    def test_actual_plan_uses_fixed_classifier_and_untrained_abstains(self):
        client = self.client(backend=self.backend)
        result = client.call("construction.plan", {"request": "堆墓"})
        self.assertEqual(result["classification"]["kind"], "broad")
        self.assertEqual(result["route"]["stages"], [1, 3])
        self.assertFalse(result["native_execution"])
        self.assertFalse(result["training_performed"])
        self.assertTrue(client.capabilities()["construction_backend_configured"])
        other = self.client(backend=HostConstructionBackend(LinearIntentClassifier()))
        result = other.call("construction.plan", {"request": "植物族堆墓"})
        self.assertEqual(result["classification"]["kind"], "ambiguous")
        self.assertEqual(result["route"]["stages"], [1])
        self.assertIn("untrained_classifier", result["classification"]["reasons"])

    def test_actual_run_reaches_existing_controller_models_binding_without_native(self):
        client = self.client(backend=self.backend)
        # Fail the test if the existing verifier is accidentally made the default.
        with patch("ygo_kito.build_pipeline.verify_goal", side_effect=AssertionError("native verifier must stay disconnected")):
            result = client.call("construction.run", self.request)
        self.assertEqual(result["status"], "construction_unresolved")
        self.assertEqual(result["classification"]["kind"], "broad")
        self.assertEqual(result["phases"][0]["stage_2"]["status"], "skipped_broad")
        attempts = result["phases"][0]["stage_3"]["attempts"]
        self.assertTrue(any(a["status"] == "concrete_candidate_cb_pending" for a in attempts))
        self.assertEqual(result["basic_cb"]["status"],"not_run")
        self.assertEqual(result["construction_candidate"]["validation"]["status"],"engine_validation_not_run")
        self.assertTrue(result["alternation_completed"])
        self.assertEqual(result["graph_model_selections"]["build_goal"]["selection"], "existing_BuildRanker")
        self.assertEqual(result["handoff"]["status"], "not_submitted")
        self.assertFalse(result["native_execution"])
        self.assertFalse(result["training_performed"])
        self.assertFalse(result["coordinator_ledger_submission"])
        self.assertEqual(result["training_status"]["graph_role_updates"], {"build_goal": 0, "build_optimizer": 0})

    def test_repeated_rpc_reuses_model_instances_but_keeps_new_session_evidence(self):
        client = self.client(backend=self.backend)
        first = client.call("construction.run", self.request)
        builder = self.backend._builders[self.task.sha256]
        adapter = next(iter(self.backend._adapters.values()))
        adapter.last_selection["build_optimizer"] = {"stale": "prior cycle, not current request"}
        second = client.call("construction.run", dict(self.request, request="未知裸名", feedback=[
            {"source": "user", "message": "Please resolve the scope"}]))
        self.assertIs(builder, self.backend._builders[self.task.sha256])
        self.assertIs(adapter, next(iter(self.backend._adapters.values())))
        self.assertIs(adapter.models["build_goal"], builder.models["build_goal"])
        self.assertEqual(set(second["graph_model_selections"]), {"build_goal"})
        self.assertTrue(all("stale" not in selection for selection in second["graph_model_selections"].values()))
        self.assertEqual([p["role"] for p in second["phases"]], ["build_goal"])
        self.assertNotEqual(first["goal_sha256"], second["goal_sha256"])
        self.assertNotEqual(first["latest_logic_sha256"], second["latest_logic_sha256"])
        self.assertEqual(second["phases"][0]["stage_2"]["status"], "needs_clarification")
        self.assertEqual(second["classification"]["kind"], "ambiguous")

    def test_rpc_schema_rejects_paths_options_hidden_fields_and_unknown_methods(self):
        client = self.client(backend=self.backend)
        for key, value in (("intent_model", "weights.json"), ("binding_data", "bindings.json"),
                           ("logic_checkpoint", "checkpoint.pt"), ("train", True),
                           ("verify_existing_goal", True), ("native", True), ("model", "provider-model")):
            with self.subTest(key=key), self.assertRaises(RemoteError) as raised:
                client.call("construction.run", dict(self.request, **{key: value}))
            self.assertEqual(raised.exception.code, "INVALID_REQUEST")
        with self.assertRaises(RemoteError) as raised:
            client.call("construction.plan", {"request": "堆墓", "path": "x"})
        self.assertEqual(raised.exception.code, "INVALID_REQUEST")
        with self.assertRaises(RemoteError) as raised:
            client.call("construction.fit", {})
        self.assertEqual(raised.exception.code, "PERMISSION_DENIED")
        with self.assertRaises(RemoteError) as raised:
            client.call("construction.run", dict(self.request, feedback=[{"source": "user", "message": "x", "model": "x"}]))
        self.assertEqual(raised.exception.code, "INVALID_REQUEST")

    def test_host_configuration_paths_are_workspace_bound_and_catalogue_is_lazy(self):
        intent = self.root / "intent.json"
        fixture_classifier().save(intent)
        config = {"intent_model": "intent.json", "binding_data": "missing-binding.json"}
        backend = HostConstructionBackend.from_config(self.root, self.root / "missing-native", config)
        with patch("ygo_kito.build_pipeline.BuildAssets", side_effect=AssertionError("plan must not load a catalogue")):
            self.assertEqual(backend.plan({"request": "堆墓"})["classification"]["kind"], "broad")
        # Use the fixed synthetic catalogue to isolate missing host binding data.
        backend._assets_factory = lambda: self.assets
        with self.assertRaises(ConstructionUnavailable):
            backend.run(self.request)
        for bad in ({**config, "binding_data": "../outside.json"}, {**config, "intent_model": str(self.root.parent / "outside.json")},
                    {**config, "native": True}):
            with self.subTest(config=bad), self.assertRaises(ContractError):
                HostConstructionBackend.from_config(self.root, self.root / "native", bad)
        with self.assertRaises(ConstructionUnavailable):
            HostConstructionBackend.from_config(self.root, self.root / "native", dict(config, intent_model="missing.json"))

    def test_missing_fixed_resources_have_explicit_rpc_error(self):
        client = self.client(backend=HostConstructionBackend(fixture_classifier()))
        with self.assertRaises(RemoteError) as raised:
            client.call("construction.run", self.request)
        self.assertEqual(raised.exception.code, "CONSTRUCTION_RESOURCES_UNAVAILABLE")
        with self.assertRaises(ContractError):
            HostConstructionBackend(None)

    def test_invalid_host_checkpoint_returns_resource_error_and_process_contract_survives(self):
        for payload in (b"not a checkpoint",b""):
            with self.subTest(payload=payload):
                path=self.root/"invalid.weights";path.write_bytes(payload)
                backend=HostConstructionBackend(fixture_classifier(),assets=self.assets,binding_data=self.binding_data,logic_checkpoint=path)
                client=self.client(backend=backend)
                with self.assertRaises(RemoteError) as raised:client.call("construction.run",self.request)
                self.assertEqual(raised.exception.code,"CONSTRUCTION_RESOURCES_UNAVAILABLE")
                self.assertEqual(client.call("construction.plan",{"request":"堆墓"})["classification"]["kind"],"broad")


if __name__ == "__main__":
    unittest.main()
