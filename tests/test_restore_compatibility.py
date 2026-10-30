"""Structural restore compatibility and explicit legacy attempt ledgers."""
import copy
import unittest

from ygo_kito.restore_compatibility import (course_binding_compatibility, models_binding_compatibility,
                                            source_drift)
from ygo_kito.scenario_course import (migrate_legacy_attempt_gap_state, validate_training_attempt_state)
from ygo_kito.validation import ContractError


def _binding():
    return {
        "kind": "ordered-scenario-course-v1",
        "config": {"course_id": "pearl-base-2207-v1", "period_id": "2022-07", "training_record_offset": 25},
        "models": {
            "kind": "course-model-binding-v1", "learning_stage": "base",
            "task_sha256": "a" * 64, "available_ids_sha256": "b" * 64,
            "resources": {"source_lock_sha256": "c" * 64, "resources": {"cards": "d" * 64}},
            "period_context": {"period_id": "2022-07", "catalog_sha256": "e" * 64},
            "source_files": {"src/ygo_kito/scenario_course.py": "1" * 64},
        },
        "source_map": {"scenario_course.py": "1" * 64, "course_models.py": "2" * 64},
        "period_context": {"period_id": "2022-07", "catalog_sha256": "e" * 64},
        "rules_sha256": "f" * 64,
        "bots": {"ice": {"stage": "bots-bo1"}},
    }


def _receipt(cursor):
    boundary = {"training_cursor": cursor, "model_sha256": "a" * 64,
                "lora": None, "observed_optimizer_step_max": float(cursor)}
    return {"kind": "course-small-game-host-receipt", "status": "failed_or_uncertain",
            "before": dict(boundary), "after": dict(boundary),
            "model_update_started": False, "model_update_completed": False, "sample_completed": False,
            "error": {"type": "NativeError",
                      "message": "CPU sample budget exhausted; no terminal reward/update claimed"},
            "retry_allowed": False, "observed_sampler_cursor": cursor,
            "observed_sampler_updates": cursor,
            "observations": {"constructor_started": True, "constructor_completed": True}}


def _record(match_id, *, complete, receipt=None):
    return {"match_id": match_id, "format": "bo1", "stage": "bots-bo1", "purpose": "train",
            "bot_id": "ice", "complete": complete, "status": "complete" if complete else "aborted",
            "winner": "opponent" if complete else None,
            "games": [{"terminal": complete, "completed": complete,
                       "winner_participant_id": "opponent" if complete else None}],
            "match_state": {}, "receipts": [] if receipt is None else [receipt]}


def _legacy_saved():
    return {
        "binding": {"config": {"training_record_offset": 0}},
        "models": {"adapters": {}, "cursors": {"duel_updates": 3, "duel_episodes": 3}},
        "records": [_record("course-train-1", complete=True),
                    _record("course-train-2", complete=False, receipt=_receipt(1)),
                    _record("course-train-3", complete=True)],
        "pending": None,
    }


class RestoreCompatibilityTests(unittest.TestCase):
    def test_source_bytes_are_audit_only(self):
        saved = _binding()
        current = copy.deepcopy(saved)
        current["source_map"] = {"scenario_course.py": "9" * 64}
        current["models"]["source_files"] = {"src/ygo_kito/scenario_course.py": "8" * 64}
        verdict = course_binding_compatibility(saved, current)
        self.assertTrue(verdict["compatible"], verdict)
        self.assertTrue(models_binding_compatibility(saved["models"], current["models"])["compatible"])

    def test_structural_change_fails_closed(self):
        saved = _binding()
        for mutate, reason in (
                (lambda b: b.__setitem__("rules_sha256", "0" * 64), "binding.rules_sha256"),
                (lambda b: b["config"].__setitem__("period_id", "2022-10"), "binding.config"),
                (lambda b: b["models"]["resources"].__setitem__("source_lock_sha256", "0" * 64),
                 "binding.models")):
            current = copy.deepcopy(saved)
            mutate(current)
            verdict = course_binding_compatibility(saved, current)
            self.assertFalse(verdict["compatible"])
            self.assertIn(reason, verdict["reasons"])

    def test_drift_reports_added_changed_removed(self):
        drift = source_drift({"a.py": "1", "b.py": "2"}, {"a.py": "9", "c.py": "3"})
        self.assertEqual(drift, {"changed": ["a.py"], "added": ["c.py"], "removed": ["b.py"]})


class LegacyAttemptGapTests(unittest.TestCase):
    def test_gap_ledger_acknowledges_the_saved_no_update_attempt(self):
        saved = _legacy_saved()
        ledger = migrate_legacy_attempt_gap_state(saved)
        self.assertEqual(ledger["next_cursor"], 4)
        self.assertIs(ledger["legacy_receipts_without_attempt_cursors"], True)
        [acknowledgment] = ledger["legacy_acknowledgments"]
        self.assertEqual(acknowledgment["match_id"], "course-train-2")
        self.assertEqual(acknowledgment["sampling_attempt_cursor"], 1)
        self.assertEqual(acknowledgment["next_sampling_attempt_cursor"], 2)
        self.assertFalse(acknowledgment["model_update_claimed"])
        self.assertFalse(acknowledgment["automatic_replay"])
        validate_training_attempt_state(saved, ledger, max_attempts=10)

    def test_gap_flag_is_required_to_skip_missing_legacy_cursors(self):
        saved = _legacy_saved()
        ledger = migrate_legacy_attempt_gap_state(saved)
        without_flag = {k: v for k, v in ledger.items()
                        if k != "legacy_receipts_without_attempt_cursors"}
        with self.assertRaises(ContractError):
            validate_training_attempt_state(saved, without_flag, max_attempts=10)

    def test_migration_refuses_a_completed_record_claiming_no_update(self):
        saved = _legacy_saved()
        saved["records"][1]["complete"] = True
        with self.assertRaises(ContractError):
            migrate_legacy_attempt_gap_state(saved)


if __name__ == "__main__":
    unittest.main()
