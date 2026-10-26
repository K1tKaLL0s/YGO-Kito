"""Passive asset/conditional arithmetic tests, without engines or model loads."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.takeover_readiness import main
from ygo_kito.takeover_readiness import artifact_inventory,collect,conditional_budget,default_config
from ygo_kito.validation import ContractError


def root_fixture(path):
    package=Path(path)/"src/ygo_kito";package.mkdir(parents=True)
    (package/"__init__.py").write_text("# Passive fixture source.\n")
    return Path(path)


def entry(root,*,category="a10_reference",sync="ready_for_audit",name="reference.json"):
    path=root/name
    path.write_text(json.dumps({"kind":"paired-A10-reference","source_commit":"a"*40,
        "summary":{"mean_seconds":90.},"executed":1,"private_text":"MUST_NOT_APPEAR_IN_REPORT"}))
    return {"artifact_id":"a10-paired","category":category,"sync_status":sync,
        "reference":{"path":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()},
        "expected_json_fields":{"/kind":"paired-A10-reference","/source_commit":"a"*40}}


class ConditionalBudgetTests(unittest.TestCase):
    def test_confirmed_slow_volume_keeps_original_budget_without_fabricated_mean(self):
        report=conditional_budget()
        self.assertIsNone(report["reference_mean_seconds"])
        self.assertIsNone(report["serial_game_seconds_sum_under_A10_reference"])
        self.assertIsNone(report["actual_CPU_wall_hours"])
        self.assertEqual(report["original_budget"],{"amount":100,"unit":"GPU_instance_hours","changed":False})
        self.assertEqual(report["current_CPU_budget_unit"],"unknown_requires_user_clarification")
        self.assertFalse(report["self_play_credits_required_coverage"])
        for period in report["per_environment"].values():
            self.assertEqual((period["completed_bo1_matches"],period["completed_bo3_matches"]),(600,400))
            self.assertEqual((period["small_games_minimum"],period["small_games_maximum_without_draw_retries"]),(1400,1800))

    def test_a10_serial_sum_and_idealized_parallel_wall_are_separate_from_cpu_prediction(self):
        report=conditional_budget(90,parallel_games=4)
        self.assertEqual(report["serial_game_seconds_sum_under_A10_reference"]["minimum"],378000)
        self.assertEqual(report["serial_game_seconds_sum_under_A10_reference"]["maximum_without_draw_retries"],486000)
        self.assertEqual(report["idealized_reference_wall_hours"]["minimum"],26.25)
        self.assertFalse(report["idealized_reference_wall_hours"]["is_actual_CPU_estimate"])
        self.assertFalse(report["linear_scaling_from_cpu_count_assumed"])
        self.assertFalse(report["fits_budget_verified"])
        self.assertIsNone(conditional_budget(90)["idealized_reference_wall_hours"])
        for bad in (True,0,-1,float("nan"),float("inf"),"90"):
            with self.subTest(bad=bad),self.assertRaises(ContractError):conditional_budget(bad)
        with self.assertRaises(ContractError):conditional_budget(90,parallel_games=True)


class PassiveTakeoverTests(unittest.TestCase):
    def test_artifact_hash_source_fields_and_sync_states_are_distinct_without_payload_leak(self):
        with tempfile.TemporaryDirectory() as temp:
            root=root_fixture(temp);spec=entry(root)
            report=artifact_inventory(root,spec)
            self.assertTrue(report["bytes_verified"]);self.assertTrue(report["report_source_fields_match"])
            self.assertFalse(report["semantics_verified"])
            self.assertNotIn("MUST_NOT_APPEAR",json.dumps(report))
            unread=deepcopy(spec);unread["sync_status"]="received_unread"
            self.assertNotIn("report_source_fields_match",artifact_inventory(root,unread))
            source=deepcopy(spec);source["sync_status"]="source_only"
            self.assertEqual(artifact_inventory(root,source)["status"],"source_only")
            missing=deepcopy(spec);missing.update(sync_status="not_received",reference=None)
            self.assertEqual(artifact_inventory(root,missing)["status"],"expected_unsynced")
            altered=deepcopy(spec);altered["reference"]["sha256"]="0"*64
            self.assertEqual(artifact_inventory(root,altered)["status"],"hash_mismatch")
            changed=deepcopy(spec);changed["expected_json_fields"]["/source_commit"]="b"*40
            self.assertEqual(artifact_inventory(root,changed)["status"],"report_source_mismatch")

    def test_source_field_boolean_and_number_are_not_interchangeable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=root_fixture(temp);spec=entry(root)
            spec["expected_json_fields"]={"/executed":True}
            self.assertEqual(artifact_inventory(root,spec)["status"],"report_source_mismatch")

    def test_pinned_a10_reference_never_becomes_local_speed_or_formal_start_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=root_fixture(temp);spec=entry(root);config=default_config()
            config.update(artifacts=[spec],a10_reference={"artifact_id":"a10-paired","mean_json_pointer":"/summary/mean_seconds"},parallel_games_assumed=2)
            with patch("ygo_kito.native_assets.verify_resources",side_effect=RuntimeError("not installed")):
                report=collect(root,config)
            self.assertEqual(report["budget"]["reference_mean_seconds"],90.)
            self.assertFalse(report["a10_reference"]["actual_CPU_speed_verified"])
            self.assertFalse(report["formal_start_ready"]);self.assertFalse(report["execution_authorized_by_this_tool"])
            self.assertIn("formal_start_requires_user_notification",report["blockers"])
            self.assertFalse(report["training_started"]);self.assertFalse(report["native_executed"])
            self.assertNotIn("MUST_NOT_APPEAR",json.dumps(report))
            self.assertIsNone(report["hardware"]["maximum_reliable_job_duration_seconds"])
            self.assertFalse(report["hardware"]["long_term_available_resources_verified"])
            config["artifacts"][0]["sync_status"]="received_unread"
            with self.assertRaises(ContractError):collect(root,config)

    def test_default_audit_reads_local_file_candidates_without_loading_or_qualifying_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root=root_fixture(temp);cache=root/".cache";cache.mkdir()
            (cache/"candidate.weights").write_bytes(b"Not a serialized model; never load this.")
            (cache/"data-index.sqlite3").write_bytes(b"Not a SQLite index; only inventory this.")
            (cache/"2022-07-engineering-dates.json").write_text("{}")
            with patch("ygo_kito.native_assets.verify_resources",side_effect=RuntimeError("not installed")),patch("subprocess.Popen",side_effect=AssertionError("no process may launch")):
                report=collect(root)
            inventory=report["local_inventory"]
            self.assertEqual(inventory["model_artifacts"]["file_count"],1)
            self.assertFalse(inventory["model_artifacts"]["model_deserialized"])
            self.assertFalse(inventory["model_artifacts"]["source_group_boundary_verified"])
            self.assertEqual(inventory["data_indices"]["file_count"],1)
            self.assertFalse(inventory["release_files"]["historical_release_completeness_verified"])
            self.assertFalse(inventory["storage_growth"]["retention_or_pruning_verified"])

    def test_workspace_escape_and_forged_reference_source_fail_before_publishing_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root=root_fixture(temp);spec=entry(root)
            spec["reference"]["path"]="../outside-private.json"
            with self.assertRaises(ContractError):artifact_inventory(root,spec)
            spec=entry(root);spec["expected_json_fields"]["/kind"]="wrong-source"
            config=default_config();config.update(artifacts=[spec],a10_reference={"artifact_id":"a10-paired","mean_json_pointer":"/summary/mean_seconds"})
            with self.assertRaises(ContractError):collect(root,config)

    def test_local_weight_symlink_is_not_read_as_a_workspace_model(self):
        with tempfile.TemporaryDirectory() as temp,tempfile.TemporaryDirectory() as external:
            root=root_fixture(temp);cache=root/".cache";cache.mkdir()
            target=Path(external)/"outside.weights";target.write_bytes(b"do not inspect")
            (cache/"alias.weights").symlink_to(target)
            with patch("ygo_kito.native_assets.verify_resources",side_effect=RuntimeError("not installed")):
                report=collect(root)
            self.assertEqual(report["local_inventory"]["model_artifacts"]["file_count"],0)
            bad=default_config();bad["schema_version"]=True
            with self.assertRaises(ContractError):collect(root,bad)

    def test_cli_has_only_audit_mode_and_sanitizes_invalid_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root=root_fixture(temp);config=root/"invalid.json"
            config.write_text('{"DO_NOT_PRINT_THIS_SECRET":')
            output=io.StringIO()
            with redirect_stdout(output):code=main(["--workspace",str(root),"--config",str(config)])
            self.assertEqual(code,2)
            self.assertNotIn("DO_NOT_PRINT_THIS_SECRET",output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["mode"],"audit_only")


if __name__=="__main__":unittest.main()
