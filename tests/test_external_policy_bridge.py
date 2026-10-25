"""Pinned-policy DTO preparation fixtures; no process/network/native/provider."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from ygo_kito.agent_driver import Client, LoopbackTransport
from ygo_kito.contracts import DecisionRequest, LegalAction, PromptInfo, SelectionChoice
from ygo_kito.external_policy_bridge import (PreparedIndexWindow, STATUS, UPSTREAM_PIN, coverage_matrix,
    coverage_from_listing_audit, coverage_from_source_inventory, attach_local_snapshot_proof)
from ygo_kito.build_contracts import digest
from ygo_kito.validation import ContractError
from tests.fixtures import request as fixture_request


def current_request():
    raw = fixture_request()
    raw["context"]["seed"] = None
    return DecisionRequest.from_dict(raw)


def selection_request():
    current = current_request()
    choices = tuple(SelectionChoice("opaque-" + str(i), 1, "hand", "hidden") for i in range(3))
    actions = (LegalAction("select-a", "select", (choices[0].ref,), 1),
               LegalAction("select-b", "select", (choices[1].ref,), 1),
               LegalAction("select-c", "select", (choices[2].ref,), 1),
               LegalAction("select-ab", "select", (choices[0].ref, choices[1].ref), 2),
               LegalAction("cancel-only-by-action-index", "pass"))
    return replace(current, actions=actions, prompt=PromptInfo(15, 1, 2, True), selection_choices=choices)


class ExternalIndexPreparationTests(unittest.TestCase):
    def reply(self, prepared, **choice):
        return dict(state_version=prepared.state_version, request_sha256=prepared.request_sha256, **choice)

    def translate(self, prepared, reply, **current):
        return prepared.translate(reply, current_request=current.get("request", prepared.request),
                                  current_state_version=current.get("state_version", prepared.state_version))

    def test_action_indexes_map_to_existing_ids_without_submitting_or_generating_responses(self):
        request = current_request()
        prepared = PreparedIndexWindow(request, "fixture-window", 0)
        for selector, index, expected in (("actionIndex", 0, "choice-1"), ("index", 1, "choice-pass")):
            result = self.translate(prepared, self.reply(prepared, **{selector: index}))
            self.assertEqual(result["params"], {"state_version": "fixture-window", "action_id": expected})
            self.assertEqual(result["status"], STATUS)
            self.assertFalse(result["action_submitted"])
            self.assertFalse(result["native_response_generated"])
        received = []
        def fixture_dispatch(message):
            received.append(message)
            return {"schema_version": 1, "id": message["id"], "ok": True,
                    "result": {"source": "local_contract_fixture", "native_executed": False}}
        client = Client(LoopbackTransport(fixture_dispatch))
        self.assertEqual(client.call(result["method"], result["params"])["source"], "local_contract_fixture")
        self.assertEqual(received[0]["method"], "duel.submit_action")

    def test_packet_contains_only_the_existing_legal_seat_dto_and_local_reference_order(self):
        prepared = PreparedIndexWindow(selection_request(), "fixture-selection", 0)
        packet = prepared.packet()
        self.assertEqual(packet["upstream_pin"], UPSTREAM_PIN)
        self.assertEqual(packet["status"], STATUS)
        self.assertTrue(packet["factorizedSelection"])
        self.assertEqual(packet["selectionCandidates"], [{"index": i, "ref": "opaque-" + str(i)} for i in range(3)])
        self.assertIsNone(packet["request"]["context"]["seed"])
        self.assertTrue(all(choice["card_id"] is None for choice in packet["request"]["selection_choices"]))
        self.assertFalse(packet["provider_connected"])
        self.assertNotIn("native_index", json.dumps(packet))
        packet["request"]["actions"][0]["action_id"] = "outside-mutation"
        self.assertEqual(prepared.request.actions[0].action_id, "select-a")

    def test_factorized_selection_matches_only_an_offered_unordered_combination(self):
        prepared = PreparedIndexWindow(selection_request(), "fixture-selection", 0)
        result = self.translate(prepared, self.reply(prepared, selectionIndexes=[1, 0]))
        self.assertEqual(result["params"]["action_id"], "select-ab")
        with self.assertRaisesRegex(ContractError, "existing legal action"):
            self.translate(prepared, self.reply(prepared, selectionIndexes=[0, 2]))
        cancel = self.translate(prepared, self.reply(prepared, actionIndex=4))
        self.assertEqual(cancel["params"]["action_id"], "cancel-only-by-action-index")

    def test_selection_duplicates_bounds_types_and_unknown_indices_are_rejected(self):
        prepared = PreparedIndexWindow(selection_request(), "fixture-selection", 0)
        for indexes in ([], [0, 0], [0, 1, 2], [-1], [3], [True], [0.5], "0"):
            with self.subTest(indexes=indexes), self.assertRaises(ContractError):
                self.translate(prepared, self.reply(prepared, selectionIndexes=indexes))

    def test_action_index_is_integer_and_never_a_raw_cancel_or_native_response(self):
        prepared = PreparedIndexWindow(current_request(), "fixture-window", 0)
        for index in (-1, 2, True, 0.5, "0", None, b"\x00"):
            with self.subTest(index=index), self.assertRaises(ContractError):
                self.translate(prepared, self.reply(prepared, actionIndex=index))

    def test_window_state_request_digest_and_current_observer_cannot_be_reused(self):
        prepared = PreparedIndexWindow(current_request(), "fixture-window", 0)
        reply = self.reply(prepared, actionIndex=0)
        for changed in (dict(reply, state_version="new-window"), dict(reply, request_sha256="0" * 64)):
            with self.assertRaisesRegex(ContractError, "stale"):
                self.translate(prepared, changed)
        with self.assertRaisesRegex(ContractError, "stale"):
            self.translate(prepared, reply, state_version="new-current-window")
        with self.assertRaisesRegex(ContractError, "stale"):
            self.translate(prepared, reply, request=replace(prepared.request, decision_id="changed-decision"))
        with self.assertRaisesRegex(ContractError, "fixed legal seat"):
            PreparedIndexWindow(prepared.request, "fixture-window", 1)
        with self.assertRaisesRegex(ContractError, "RNG"):
            PreparedIndexWindow(DecisionRequest.from_dict(fixture_request()), "fixture-window", 0)

    def test_unknown_fields_mixed_selectors_and_non_dto_inputs_are_rejected(self):
        prepared = PreparedIndexWindow(current_request(), "fixture-window", 0)
        for selectors in ({}, {"actionIndex": 0, "index": 0}, {"actionIndex": 0, "selectionIndexes": []},
                          {"response": [1, 2]}, {"actionIndex": 0, "hidden_hand": [123]}):
            with self.subTest(selectors=selectors), self.assertRaises(ContractError):
                self.translate(prepared, self.reply(prepared, **selectors))
        with self.assertRaises(ContractError):
            PreparedIndexWindow(prepared.request.to_dict(), "fixture-window", 0)

    def test_incremental_order_sum_and_ambiguous_refs_use_action_ids_instead(self):
        request = selection_request()
        for kind in (20, 26, 25, 23):
            # Remove temporary references in the same validated DTO operation.
            window = replace(request, prompt=PromptInfo(kind, 1, 2), selection_choices=(),
                             actions=(LegalAction("existing-operation", "select"),))
            prepared = PreparedIndexWindow(window, "fixture-window", 0)
            self.assertFalse(prepared.packet()["factorizedSelection"])
            with self.assertRaisesRegex(ContractError, "unsupported"):
                self.translate(prepared, self.reply(prepared, selectionIndexes=[0]))
        ambiguous = replace(request, actions=(request.actions[0], replace(request.actions[0], action_id="same-refs-other-operation")))
        prepared = PreparedIndexWindow(ambiguous, "fixture-window", 0)
        self.assertFalse(prepared.packet()["factorizedSelection"])
        with self.assertRaisesRegex(ContractError, "ambiguous"):
            self.translate(prepared, self.reply(prepared, selectionIndexes=[0]))


class StaticCoverageMatrixTests(unittest.TestCase):
    def inputs(self):
        samples = [{"sample_id": name, "deck_sha256": str(i) * 64, "artifact_sha256": "f" * 64,
                    "source_pin": UPSTREAM_PIN, "source_path": "skill/resources/windbot/Decks/" + name + ".ydk"}
                   for i, name in enumerate(("source-sample-a", "source-sample-b"), 1)]
        drivers = [{"driver_id": mode, "source_pin": UPSTREAM_PIN,
                    "source_path": "skill/resources/windbot/Game/AI/" + mode + ".cs", "mode": mode}
                   for mode in ("deck_executor", "external_policy_only")]
        return ["2022-07", "2022-10", "2026-10"], samples, drivers

    def test_cartesian_matrix_is_complete_and_never_infers_runtime_from_static_listing(self):
        periods, samples, drivers = self.inputs()
        check = {"period_id": periods[0], "sample_id": samples[0]["sample_id"],
                 "deck_sha256": samples[0]["deck_sha256"], "status": "checked_under_supplied_evidence", "evidence_sha256": "a" * 64}
        result = coverage_matrix(periods, samples, drivers, listing_checks=[check])
        self.assertEqual(len(result["rows"]), 12)
        self.assertEqual(len({row["row_id"] for row in result["rows"]}), 12)
        self.assertEqual(sum(row["listing"]["status"] == check["status"] for row in result["rows"]), 2)
        for row in result["rows"]:
            self.assertFalse(row["operation_qualified"])
            self.assertFalse(row["strength_qualified"])
            self.assertEqual(row["driver_execution"], "not_run")
            self.assertEqual(row["deck_driver_match"], "not_checked")
        self.assertFalse(result["formal_training_ready"])
        self.assertFalse(result["native_executed"])
        self.assertFalse(result["qualification_inferred_from_listing"])
        self.assertEqual(result, coverage_matrix(periods, samples, drivers, listing_checks=[check]))

    def test_unknown_missing_or_forged_static_records_do_not_become_qualification(self):
        periods, samples, drivers = self.inputs()
        for mutation in ("sample_pin", "driver_pin", "duplicate_sample", "duplicate_driver", "escape", "bad_digest"):
            p, s, d = deepcopy((periods, samples, drivers))
            if mutation == "sample_pin": s[0]["source_pin"] = "0" * 40
            elif mutation == "driver_pin": d[0]["source_pin"] = "0" * 40
            elif mutation == "duplicate_sample": s.append(deepcopy(s[0]))
            elif mutation == "duplicate_driver": d.append(deepcopy(d[0]))
            elif mutation == "escape": d[0]["source_path"] = "../outside.cs"
            else: s[0]["deck_sha256"] = "unknown"
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                coverage_matrix(p, s, d)
        evidence = {"period_id": periods[0], "sample_id": samples[0]["sample_id"], "deck_sha256": "0" * 64,
                    "status": "checked_under_supplied_evidence", "evidence_sha256": "a" * 64}
        with self.assertRaisesRegex(ContractError, "different sample"):
            coverage_matrix(periods, samples, drivers, listing_checks=[evidence])
        evidence.update(deck_sha256=samples[0]["deck_sha256"], status="strength_qualified")
        with self.assertRaisesRegex(ContractError, "qualification"):
            coverage_matrix(periods, samples, drivers, listing_checks=[evidence])

    def test_source_audit_projection_uses_pinned_samples_and_preserves_blocked_cutoff(self):
        periods, samples, drivers = self.inputs()
        audit = {"schema_version": 1, "periods": {p: {} for p in periods}, "samples": []}
        for sample in samples:
            audit["samples"].append({"sample_id": sample["sample_id"], "dataset_kind": "third_party_sample_not_user_deck",
                "user_deck": False, "deck_sha256": sample["deck_sha256"],
                "source": {key: sample[key] for key in ("artifact_sha256", "source_pin", "source_path")},
                "checks": [{"period_id": p, "historical_listing_status": "blocked_cutoff_unspecified" if p == "2026-10" else "unverified"}
                           for p in periods]})
        audit["samples"].append({"dataset_kind": "engineering_fixture_not_user_deck"})
        for blocked in ("blocked_cutoff_unspecified", "blocked_future_cutoff_staging_only"):
            for sample in audit["samples"]:
                for check in sample.get("checks", []):
                    if check["period_id"] == "2026-10": check["historical_listing_status"] = blocked
            matrix = coverage_from_listing_audit(audit, drivers)
            self.assertEqual(len(matrix["samples"]), 2)
            self.assertEqual(len(matrix["rows"]), 12)
            current_rows = [row for row in matrix["rows"] if row["period_id"] == "2026-10"]
            self.assertTrue(all(row["listing"]["status"] == "blocked" for row in current_rows))
            self.assertTrue(all(row["listing"]["source_status"] == blocked for row in current_rows))
            self.assertTrue(all(not row["strength_qualified"] for row in matrix["rows"]))
            self.assertIn("listing_audit_sha256", matrix)

    def local_proof_fixture(self, period):
        # Explicit trusted-producer summary fixture, not an actual native run.
        scope = {"period_id": period, "period_context": {"period_id": period},
            "versions": current_request().context.versions.__dict__, "resources": {"library": "a" * 64, "cards": "b" * 64},
            "profile_sha256": "c" * 64, "own_deck_sha256": "d" * 64, "opponent_deck_sha256": "e" * 64,
            "model_sha256": "f" * 64, "driver_version": "frozen-duel-greedy-v1",
            "driver_implementation_sha256": "1" * 64, "controller": "local_snapshot"}
        proof = {"schema_version": 1, "kind": "actual-period-local-snapshot-engineering", "scope": scope,
            "source_component": {"name": "components.duel", "group_checkpoint_sha256": "2" * 64,
                "model_sha256": scope["model_sha256"], "completed_boundary": "complete-episode",
                "source_group_boundary": "complete-workflow-stage", "completed_updates": 1,
                "updated_base_component": True, "lora_snapshot": False, "extracted_artifact_sha256": "3" * 64},
            "passed": {key: True for key in ("normal_sampling", "natural_terminal", "private_replay", "source_checkpoint_restore",
                "host_reload_binding", "actor_rebind", "weights_frozen")}, "training_updates_this_check": 0,
            "historical_training_verified": False, "historical_rules_verified": False, "strength_qualified": False,
            "applies_to_matrix_rows": []}
        proof["summary_sha256"] = digest(proof)
        return proof

    def test_trusted_local_proof_is_scope_bound_and_never_marks_windbot_rows_run(self):
        periods, samples, drivers = self.inputs()
        matrix = coverage_matrix(periods, samples, drivers)
        proof = self.local_proof_fixture(periods[0])
        attached = attach_local_snapshot_proof(matrix, proof, expected_scope=deepcopy(proof["scope"]))
        record = attached["local_operational_references"][0]
        self.assertTrue(record["normal_operational"])
        self.assertEqual(record["applies_to_matrix_rows"], [])
        self.assertFalse(record["training_checkpoint_recovery_verified"])
        self.assertFalse(record["historical_rules_verified"])
        self.assertFalse(record["strength_qualified"])
        self.assertTrue(all(not row["normal_operational"] and row["driver_execution"] == "not_run" for row in attached["rows"]))
        self.assertEqual(attached, attach_local_snapshot_proof(attached, proof, expected_scope=proof["scope"]))
        with self.assertRaisesRegex(ContractError, "exact expected scope"):
            attach_local_snapshot_proof(matrix, proof, expected_scope=dict(proof["scope"], profile_sha256="0" * 64))

    def test_local_summary_hash_failed_checks_training_or_cross_driver_qualification_rejected(self):
        periods, samples, drivers = self.inputs()
        matrix = coverage_matrix(periods, samples, drivers)
        proof = self.local_proof_fixture(periods[0])
        for mutation in ("hash", "failed_check", "training", "strength", "foreign_row", "component"):
            changed = deepcopy(proof)
            if mutation == "hash": changed["summary_sha256"] = "0" * 64
            else:
                if mutation == "failed_check": changed["passed"]["private_replay"] = False
                elif mutation == "training": changed["training_updates_this_check"] = 1
                elif mutation == "strength": changed["strength_qualified"] = True
                elif mutation == "foreign_row": changed["applies_to_matrix_rows"] = [matrix["rows"][0]["row_id"]]
                else: changed["source_component"]["model_sha256"] = "0" * 64
                changed.pop("summary_sha256"); changed["summary_sha256"] = digest(changed)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                attach_local_snapshot_proof(matrix, changed, expected_scope=proof["scope"])
