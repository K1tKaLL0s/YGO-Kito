"""Normal current-core inference of an existing updated project CPU component.

No training resume across implementation bindings, optimizer update, provider,
fault injection or historical/competitive qualification is performed here.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

import torch

from integration_tests.test_period_runtime import engineering_period_fixture
from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.duel_model import parameter_digest
from ygo_kito.contracts import ActionSelection
from ygo_kito.normal_duel import request_digest
from ygo_kito.opponent_pool import replay_private
from ygo_kito.period_host import load_period_host, period_host_operation
from ygo_kito.period_runtime import PeriodBuildAssets
from ygo_kito.training_input import _profile
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


def existing_updated_base_component(destination):
    """Copy one actual saved base component, retaining its original bindings.

    Group save suspends the adapters. This extracts its updated base duel, not
    the latest LoRA policy and not a training checkpoint migration.
    """
    candidates = sorted(CACHE.glob("period-group-normal-*/runs/normal-group/checkpoints/local-step-7.weights"))
    for source in candidates:
        original = source.read_bytes()
        group = torch.load(source, map_location="cpu", weights_only=True)
        component = group.get("components", {}).get("duel", {})
        if (group.get("boundary") != "complete-workflow-stage" or group.get("cursor", {}).get("phase") != "done" or
                component.get("boundary") != "complete-episode" or component.get("updates", 0) < 1 or
                component.get("updates") != component.get("episode_cursor")):
            continue
        path = destination / "updated-base-duel-component.weights"
        torch.save(component, path)
        if hashlib.sha256(source.read_bytes()).hexdigest() != hashlib.sha256(original).hexdigest():
            raise AssertionError("source group artifact changed during read-only extraction")
        provenance = {"group_checkpoint_sha256": hashlib.sha256(original).hexdigest(), "name": "components.duel",
            "source_group_boundary": group["boundary"], "completed_boundary": component["boundary"],
            "model_sha256": component["model_sha256"], "completed_updates": component["updates"],
            "updated_base_component": True, "lora_snapshot": False,
            "extracted_artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        (destination / "source-component.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
        return path, component, provenance
    raise AssertionError("an existing actually updated project CPU group component is required; no fake completion fallback")


class RealPeriodSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        # Retain allowed engineering resources/model receipts for the root's
        # coverage audit. These do not contain a formal user roster.
        cls.folder = Path(tempfile.mkdtemp(prefix="period-snapshot-normal-", dir=CACHE))
        proof_path = CACHE / ("pretraining-engine/period-snapshot-" + getattr(cls, "requested_period", "2022-07") + "-proof.json")
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        proof_path.write_text(json.dumps({"schema_version": 1, "status": "pending-normal-engineering-check"}), encoding="utf-8")
        intake, policy, assets, codes = engineering_period_fixture(cls.folder)
        checkpoint, component, cls.source_component = existing_updated_base_component(cls.folder)
        cls.checkpoint = checkpoint
        cls.period = getattr(cls, "requested_period", "2022-07")
        cutoff = {"2022-07": "2022-09-30", "2022-10": "2022-12-31"}[cls.period]
        environment = intake["environments"][cls.period]
        release = CACHE / environment["releases"]["path"]
        dates = json.loads(release.read_text(encoding="utf-8"))
        dates["release_cutoff"] = cutoff
        release.write_text(json.dumps(dates), encoding="utf-8")
        environment["release_cutoff"] = cutoff
        environment["releases"]["sha256"] = hashlib.sha256(release.read_bytes()).hexdigest()
        runtime = PeriodBuildAssets(CACHE, cls.period, environment, CACHE, evidence_source="engineering_fixture")
        source_label = "project-CPU-group-updated-base-duel-component; adapters-suspended; group-sha=" + cls.source_component["group_checkpoint_sha256"]
        ordinal = ("2022-07", "2022-10", "2026-10").index(cls.period)
        actor = DeckParts.from_dict(intake["slots"][ordinal]["deck"]["content"])
        slots = {slot["slot_id"]: slot for slot in intake["slots"]}
        for partition in policy["periods"][cls.period]["partitions"].values():
            for assigned in partition["opponents"]:
                received = slots[assigned["slot_id"]]
                profile = _profile(actor, DeckParts.from_dict(received["deck"]["content"]), 5)
                baseline = runtime.bind_rule_opponent(profile, assigned["binding"]["opponent_id"])
                assigned["binding"] = deepcopy(baseline.binding)
        slot = intake["slots"][9]  # Explicit validation opponent-07.
        slot["controller"] = {"controller": "local_snapshot", "provider": "local-pytorch-cpu", "model": component["model_sha256"],
                              "driver_version": "frozen-duel-greedy-v1"}
        profile = _profile(actor, DeckParts.from_dict(slot["deck"]["content"]), 5)
        frozen = runtime.bind_snapshot_opponent(profile, slot["slot_id"], checkpoint,
            cls.source_component["extracted_artifact_sha256"], component["model_sha256"],
            model_source=source_label, migration="explicit-inference-migration")
        policy["periods"][cls.period]["partitions"]["validation"]["opponents"][0]["binding"] = deepcopy(frozen.binding)
        for period in (p for p in ("2022-07", "2022-10", "2026-10") if p != cls.period):
            intake["environments"][period].update(release_cutoff=None, catalog=None, releases=None, banlist=None)
            policy["periods"][period]["versions"] = None
            for partition in policy["periods"][period]["partitions"].values():
                partition.update(opponents=None, seeds=None, policy_seed=None)
        for environment in intake["environments"].values():
            for kind in ("catalog", "releases", "banlist"):
                if environment[kind] is not None: environment[kind]["path"] = ".cache/" + environment[kind]["path"]
        intake_path, policy_path = cls.folder / "intake.json", cls.folder / "policy.json"
        intake_path.write_text(json.dumps(intake), encoding="utf-8")
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        descriptor = {"schema_version": 1, "scope": "selected-period", "period_id": cls.period,
            "intake": str(intake_path.relative_to(ROOT)), "policy": str(policy_path.relative_to(ROOT)),
            "native_roots": {cls.period: ".cache"}, "snapshots": {cls.period: {slot["slot_id"]: {
                "path": str(checkpoint.relative_to(ROOT)), "sha256": cls.source_component["extracted_artifact_sha256"],
                "model_source": source_label, "migration": "explicit-inference-migration"}}}}
        (cls.folder / "host-descriptor.json").write_text(json.dumps(descriptor), encoding="utf-8")
        cls.config = tempfile.TemporaryDirectory(prefix="period-snapshot-host-", dir=ROOT / "configs")
        descriptor_path = Path(cls.config.name) / "host.json"
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        cls.recipe = {"period_inputs": str(descriptor_path.relative_to(ROOT))}
        with period_host_operation():
            cls.host = load_period_host(cls.recipe, workspace=ROOT)
        selected = cls.host.for_runner("validation")
        cls.opponent = cls.host.opponent_for(selected["opponent_binding"], selected["profile"])
        cls.selection = selected
        cls.actor = cls.host.assets.bind_rule_opponent(cls.opponent.profile, "visible-engineering-actor", seat=0)
        cls.actor_policy_rng = torch.get_rng_state().clone()
        before = parameter_digest(cls.opponent.policy.model)
        audit = []
        started = time.monotonic()
        with cls.host.assets.engine_factory(CACHE, deck_profile=cls.opponent.profile, seed=selected["seed"], selection_key="de" * 16) as engine:
            request = engine.next_decision()
            while request is not None and len(audit) < 1500 and time.monotonic() - started < 30:
                if request.context.seed is not None: raise AssertionError("duel seed leaked into a policy DTO")
                adapter = cls.actor if request.observation.observer == 0 else cls.opponent
                action = adapter.select(request)
                audit.append({"player": request.observation.observer, "request_sha256": request_digest(request), "action_id": action.action_id})
                engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
                request = engine.next_decision()
            if request is not None or engine.outcome is None or not engine.events or engine.events[-1]["kind"] != 5:
                raise AssertionError("normal snapshot match did not naturally terminate inside its unchanged check bound")
            trace = {"schema_version": 1, "kind": "registered-opponent-private-replay-v1", "name": "engineering-period-model-opponent",
                "profile": cls.opponent.profile, "seed_audit_only": selected["seed"], "selection_key_audit_only": engine._selection_seed,
                "resources": engine.receipt, "responses": audit, "events": engine.events, "outcome": engine.outcome,
                "final_observations": [json.loads(json.dumps(asdict(engine._observation(p)))) for p in (0, 1)],
                "result": {"turns": engine.turn, "life_points": engine.life_points}, "opponent_binding": cls.opponent.binding}
        cls.episode = {"summary": {"outcome": trace["outcome"], "opponent_binding": cls.opponent.binding}, "steps": audit}
        cls.replay = replay_private(CACHE, trace, engine_factory=cls.host.assets.engine_factory)
        (cls.folder / "private-replay.json").write_text(json.dumps(trace), encoding="utf-8")
        if before != parameter_digest(cls.opponent.policy.model):
            raise AssertionError("frozen snapshot changed while sampling")
        cls.checks = {}

    @classmethod
    def tearDownClass(cls):
        cls.config.cleanup()
        required = {"normal_sampling", "natural_terminal", "private_replay", "source_checkpoint_restore",
                    "host_reload_binding", "actor_rebind", "weights_frozen"}
        if set(cls.checks) == required and all(cls.checks.values()):
            binding = cls.opponent.binding
            summary = {"schema_version": 1, "kind": "actual-period-local-snapshot-engineering", "scope": {
                "period_id": cls.period, "period_context": cls.host.assets.period_context,
                "versions": cls.host.assets.environment["versions"], "resources": cls.host.assets.receipt["resources"],
                **{key: binding[key] for key in ("profile_sha256", "own_deck_sha256", "opponent_deck_sha256", "model_sha256",
                    "driver_version", "driver_implementation_sha256", "controller")}},
                "source_component": cls.source_component, "passed": cls.checks, "training_updates_this_check": 0,
                "historical_training_verified": False, "historical_rules_verified": False, "strength_qualified": False,
                "applies_to_matrix_rows": [], "native_executed": True, "fault_injection_performed": False}
            summary["summary_sha256"] = digest(summary)
            path = CACHE / ("pretraining-engine/period-snapshot-" + cls.period + "-proof.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def test_actual_snapshot_normal_sample_and_exact_period_replay_without_updates(self):
        self.assertIsNotNone(self.episode["summary"]["outcome"])
        self.assertTrue(self.episode["steps"])
        self.assertTrue(torch.equal(torch.get_rng_state(), self.actor_policy_rng))
        self.assertEqual(self.replay["callback_errors"], 0)
        self.assertTrue(self.replay["natural_terminal"])
        self.assertTrue(self.replay["replay_verified"])
        self.assertEqual(self.episode["summary"]["opponent_binding"], self.opponent.binding)
        self.assertEqual(set(self.host.loaded.assets), {self.period})
        self.assertEqual(self.host.loaded.manifest["scope"], "selected-period")
        with self.assertRaises(ContractError): self.host.loaded.for_runner("2026-10", "validation")
        self.checks.update(normal_sampling=True, natural_terminal=True, private_replay=True, weights_frozen=True)

    def test_actual_source_model_reload_and_actor_rebind_keep_frozen_identity(self):
        global_rng = torch.get_rng_state().clone()
        with period_host_operation():
            again = load_period_host(self.recipe, workspace=ROOT)
        self.assertTrue(torch.equal(torch.get_rng_state(), global_rng))
        self.assertTrue(torch.equal(torch.get_rng_state(), self.actor_policy_rng))
        selection = again.for_runner("validation")
        restored = again.opponent_for(selection["opponent_binding"], selection["profile"])
        self.assertEqual(restored.binding, self.opponent.binding)
        self.assertEqual(parameter_digest(restored.policy.model), self.source_component["model_sha256"])
        self.assertEqual(restored.policy.encoder.vocab_sha256, self.opponent.policy.encoder.vocab_sha256)
        self.assertFalse(restored.model_provenance["historical_training_verified"])
        self.assertIsNone(restored.model_provenance["source_period_context"])
        self.assertEqual(restored.model_provenance["migration"], "explicit-inference-migration")
        old = list(selection["main_deck"].main)
        replacement = next(c for c in sorted(again.assets.allowed_card_ids) if c not in old)
        revised = again.rebind_actor(restored.binding, DeckParts((replacement,) + tuple(old[1:])), "validation")
        self.assertNotEqual(revised.binding["own_deck_sha256"], restored.binding["own_deck_sha256"])
        self.assertEqual(revised.binding["model_sha256"], restored.binding["model_sha256"])
        self.assertEqual(revised.model_provenance["source_binding_sha256"], restored.model_provenance["source_binding_sha256"])
        with again.assets.engine_factory(CACHE, deck_profile=revised.profile, seed=7) as engine:
            self.assertIsNotNone(engine.next_decision())
            self.assertEqual(engine.context.versions, revised.versions)
        self.checks.update(source_checkpoint_restore=True, host_reload_binding=True, actor_rebind=True)


class RealOctoberPeriodSnapshotTests(RealPeriodSnapshotTests):
    requested_period = "2022-10"


if __name__ == "__main__":
    unittest.main()
