"""DP reference client to real construction RPC, with synthetic catalogue data.

These are local protocol/CPU composition checks, not a provider connection or
real card-effect/duel evidence. The only fit is the existing small synthetic
intent-classifier fixture. No graph/deck model training or native call is run.
"""

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from threading import Event
import time
from types import SimpleNamespace
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
        self.assertEqual(result["status"], "construction_suspended")
        self.assertEqual(result["classification"]["kind"], "broad")
        self.assertEqual(result["phases"][0]["stage_2"]["status"], "deferred_to_optimizer")
        self.assertEqual(result["phases"][0]["stage_3"]["status"], "effect_draft_ready")
        self.assertNotIn("proposal_deck_sha256", result["phases"][0])
        self.assertEqual(result["handoffs"][0]["role"], "build_optimizer")
        self.assertEqual(result["handoffs"][0]["input_draft_sha256"], result["effect_draft"]["logic_sha256"])
        self.assertEqual(result["basic_cb"]["status"],"not_run")
        self.assertEqual(result["construction_candidate"]["validation"]["status"],"construction_pending")
        self.assertFalse(result["construction_passed"])
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


class ConstructionSessionRPCTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        from tests.test_construction_functional_flow import fixture
        self.task, self.assets, self.graph, _, decks, _ = fixture()
        self.deck = decks[-1].to_dict()
        self.request = dict(request='fixed construction objective', task=self.task.to_dict(),
                            required_tags=[asdict(self.graph.nodes[0].tags[0])])

    def host(self, directory='manager', **runtime):
        from ygo_kito.construction_fill import construction_cycle

        backend = HostConstructionBackend(LinearIntentClassifier(), assets=self.assets, runtime=runtime)

        def run(session, *, scopes, base, verifier, cb_authorized, **options):
            self.assertIsNone(verifier)
            self.assertFalse(cb_authorized)
            return construction_cycle(session, self.assets, {}, cb_authorized=cb_authorized, **options)

        backend._controller = lambda *_args: (self.assets, SimpleNamespace(run=run, graph_adapter=SimpleNamespace(device='cpu')))
        backend._model_binding = lambda *_args: 'fixed static test model binding'
        bridge = AgentBridge(self.root, self.root/directory, self.root/'no-native', role='manager',
                             construction_backend=backend)
        self.addCleanup(bridge.close)
        return Client(LoopbackTransport(bridge.dispatch)), bridge, backend

    def wait_for(self, client, session_id):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            result = client.call('construction.progress', {'session_id': session_id})
            if not result['active']:
                return result
            time.sleep(.01)
        self.fail('construction worker did not reach a safe boundary')

    def test_rpc_cancellation_retry_restart_and_binding_isolation(self):
        from ygo_kito.build_contracts import DeckParts
        from ygo_kito.construction_checkpoint import ConstructionCheckpoint, LEGACY_KERNEL_FILENAME

        client, bridge, backend = self.host(mode='development', slice_seconds=2., iterations=1)
        entered, resumed, release = Event(), Event(), Event()
        calls = []
        partial = DeckParts((self.deck['main'][0],)).to_dict()

        def step(session, *_args, pause_requested, **options):
            calls.append(options)
            state = session.construction_progress
            if state is None:
                session.submit_logic(self.graph, role='build_goal', reason='static RPC graph')
                row = dict(deck=partial, deck_sha256=digest(partial), layer_evaluation=None)
                state = dict(schema_version=3, task_sha256=self.task.sha256, logic_sha256=self.graph.sha256,
                    candidate=row, candidate_version=1, iteration=0, status='optimizing', quality_policy=None,
                    handoffs=[dict(role='build_goal', output_deck_sha256=digest(partial), candidate_version=1)])
                entered.set()
                if not backend._jobs[next(iter(backend._jobs))].pause.wait(4):
                    self.fail('cancellation did not reach the active construction session')
                self.assertTrue(pause_requested())
                reason = 'user_pause'
            else:
                self.assertEqual(state['candidate']['deck'], partial)
                self.assertEqual(session.task.sha256, self.task.sha256)
                self.assertEqual(session.logic.sha256, self.graph.sha256)
                resumed.set()
                self.assertTrue(release.wait(4))
                self.assertFalse(pause_requested())
                reason = 'fixture_completed'
            session.construction_progress = state
            return dict(status='construction_suspended', construction_passed=False, phases=[],
                        stop_reason=reason, continuation=state, construction_candidate={'deck': partial})

        with patch('ygo_kito.construction_fill._construction_cycle', side_effect=step):
            started = client.call('construction.start', self.request, request_id='start-fixed')
            ident = started['session_id']
            self.assertTrue(entered.wait(4))
            self.assertEqual(client.call('construction.start', self.request, request_id='start-fixed')['session_id'], ident)
            with self.assertRaises(RemoteError):
                client.call('construction.start', dict(self.request, request='another objective'), request_id='start-fixed')
            with self.assertRaises(RemoteError):
                client.call('construction.continue', dict(session_id=ident, revision=1))
            with self.assertRaises(RemoteError):
                client.call('construction.progress', {'session_id': '../kernel.json'})
            other, _, _ = self.host('other-manager')
            with self.assertRaises(RemoteError):
                other.call('construction.progress', {'session_id': ident})
            competing, _, _ = self.host(mode='development', slice_seconds=2., iterations=1)
            with self.assertRaises(RemoteError) as conflict:
                competing.call('construction.progress', {'session_id': ident})
            self.assertEqual(conflict.exception.code, 'CONSTRUCTION_RESOURCES_UNAVAILABLE')
            stopped = client.call('construction.cancel', dict(session_id=ident, attempt=1))
            self.assertTrue(stopped['cancel_requested'])
            paused = self.wait_for(client, ident)
            self.assertEqual((paused['status'], paused['stop_reason']), ('paused', 'user_pause'))
            self.assertEqual(paused['candidate'], partial)
            path = self.root/'manager'/'construction'/ident/'kernel.json.gz'
            saved = ConstructionCheckpoint.read(path)
            self.assertEqual(saved['revision'], paused['revision'])
            bridge.close()

            legacy = ConstructionCheckpoint(path.with_name(LEGACY_KERNEL_FILENAME), revision=saved['revision']-1)
            legacy.commit(saved['state'], stop_reason=saved['stop_reason'])
            path.unlink()
            next_client, next_bridge, _ = self.host(mode='development', slice_seconds=2., iterations=1)
            self.assertEqual(next_client.call('construction.progress', {'session_id': ident})['candidate'], partial)
            resume = dict(session_id=ident, revision=paused['revision'])
            self.assertEqual(next_client.call('construction.continue', resume, request_id='continue-fixed')['attempt'], 2)
            self.assertTrue(resumed.wait(4))
            replay = next_client.call('construction.continue', resume, request_id='continue-fixed')
            self.assertEqual(replay['attempt'], 2)
            stale_cancel = next_client.call('construction.cancel', dict(session_id=ident, attempt=1))
            self.assertFalse(stale_cancel['cancel_requested'])
            release.set()
            finished = self.wait_for(next_client, ident)
            self.assertEqual(finished['status'], 'finished', finished)
            self.assertEqual(finished['goal_sha256'], started['goal_sha256'])
            self.assertEqual(len(calls), 2)
            next_bridge.close()

            changed, _, changed_backend = self.host(mode='development', slice_seconds=2., iterations=1)
            changed_backend._model_binding = lambda *_args: 'different loaded weights'
            changed.call('construction.continue', dict(session_id=ident, revision=finished['revision']))
            rejected = self.wait_for(changed, ident)
            self.assertIn('models or resources have changed', rejected['error']['message'])
            self.assertEqual(rejected['revision'], finished['revision'])
            self.assertEqual(len(calls), 2)

    def test_online_rpc_drains_with_shared_scheduler_and_rejects_overrides(self):
        client, _, _ = self.host(mode='online', seconds=0., slice_seconds=1., iterations=4)
        for key in ('path', 'model', 'train', 'native', 'provider', 'seconds', 'run_mode'):
            with self.subTest(key=key), self.assertRaises(RemoteError) as rejected:
                client.call('construction.start', dict(self.request, **{key: True}))
            self.assertEqual(rejected.exception.code, 'INVALID_REQUEST')
        gate = dict(status='pending', reasons=['quality_evaluation_incomplete'])

        def step(session, *_args, **options):
            self.assertEqual(options['max_candidates'], 0)
            self.assertEqual(options['max_iterations'], 1)
            self.assertFalse(options['cb_authorized'])
            session.construction_progress = {}
            return dict(status='construction_suspended', construction_passed=False, phases=[],
                        stop_reason='iteration_slice_exhausted', continuation={}, construction_gate=gate)

        with patch('ygo_kito.construction_fill._construction_cycle', side_effect=step) as cycle:
            started = client.call('construction.start', self.request)
            result = self.wait_for(client, started['session_id'])
        self.assertEqual(cycle.call_count, 1)
        self.assertTrue(result['execution']['deadline_reached'])
        self.assertEqual(result['stop_reason'], 'online_deadline_advanced')
        self.assertEqual(result['gate_reasons'], gate['reasons'])
        self.assertFalse(result['construction_passed'])


if __name__ == "__main__":
    unittest.main()
