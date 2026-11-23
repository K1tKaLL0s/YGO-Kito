"""CPU tests for initial S2->S3-S5 admission vs post-admission feedback routing (0 static scoring calls)."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.autonomous_construction import AutonomousConstructionKernel
from ygo_kito.basic_cb_scope import VERSION as CB_SCOPE_VERSION
from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_feedback import compare_feedback_revision
from ygo_kito.build_model import BuildModelConfig
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.build_semantics import accepted_status
from ygo_kito.build_training import BuildTrainer, BuildTrainingConfig
from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
from ygo_kito.construction_logic import ConstructionSession
from ygo_kito.construction_progress import (
    host_construction_quality,
    is_initial_admitted,
    restore_progress,
)
from ygo_kito.coordinator_model import CoordinatorModelConfig, CoordinatorTrainer
from ygo_kito.course_admission_policy import CourseAdmissionPolicy
from ygo_kito.effect_lua import LuaEffectSource
from ygo_kito.scenario_course import ScenarioCourse
from ygo_kito.training_admission import require_training_admission


ROOT = Path(__file__).resolve().parents[1]


def _make_cb_proof(cand_task, deck, assets, *, success=True):
    route = cand_task.goal.get("route_goal") or {}
    card_id = route.get("card_id", deck.main[0])
    return {
        "status": accepted_status(cand_task) if success else "failed",
        "task_sha256": cand_task.sha256,
        "deck_sha256": digest(deck.to_dict()),
        "search_started": True,
        "exploration": {"nodes_expanded": 3 if success else 0},
        "route_evidence": {
            "basic_cb_scope": {
                "version": CB_SCOPE_VERSION,
                "unknown": [],
                "random_result_branches_expanded": False,
                "steps": [{"kind": route.get("kind", "xyz_summon"), "card_id": card_id}],
            },
        },
        "normal_completion": True,
    }


def _feedback_fixture():
    raw = json.loads((ROOT / "configs/build-semantic-engineering-v4.json").read_text(encoding="utf-8"))
    raw.update(
        task_id="synthetic-feedback-boundary",
        pool=list(range(1, 38)),
        requirements=[],
        sizes={"main": 40, "extra": 1, "side": 0},
        candidate_budget=25,
    )
    raw["goal"] = {
        "kind": "deck_constraints",
        "constraints": [{
            "id": "theme",
            "zones": ["main"],
            "predicate": {"field": "setcode", "value": 0x2c3},
            "minimum": 1,
            "maximum": 40,
        }],
        "preferences": [],
    }
    task = BuildTask.from_dict(raw)
    assets = BuildAssets.__new__(BuildAssets)
    assets.root = ROOT
    assets.environment = deepcopy(task.environment)
    assets.limits = {}
    assets.receipt = {"resources": {"cards": "a" * 64, "scripts": "b" * 64}, "engineering_fixture": True}
    rows = {}
    for cid in range(1, 37):
        is_odd = (cid % 2 == 1)
        rows[cid] = {
            "id": cid,
            "alias": 0,
            "ot": 1,
            "type": 33 if cid in (1, 3, 5, 7, 9, 11) else 17,
            "race": 1,
            "setcode": 0x2c3 if is_odd else 0x4d5,
            "level": 4,
            "attribute": 1,
            "atk": 1500,
            "def": 1000,
            "name": f"synthetic-{cid}",
            "desc": "①：把卡组1只怪兽加入手卡。" if cid in (1, 3, 5, 7, 9, 11) else "Synthetic vanilla monster.",
        }
    rows[37] = {
        "id": 37,
        "alias": 0,
        "ot": 1,
        "type": 0x800001,
        "race": 1,
        "setcode": 0x4d5,
        "level": 4,
        "attribute": 1,
        "atk": 2000,
        "def": 2000,
        "name": "synthetic-rank4-xyz",
        "desc": "",
    }
    assets.rows = rows

    script = b"""function effect.filter(c)
  return c:IsCode(2) and c:IsAbleToHand()
end
function effect.target(e,tp,eg,ep,ev,re,r,rp,chk)
  if chk==0 then return Duel.IsExistingMatchingCard(effect.filter,tp,LOCATION_DECK,0,1,nil) end
end
function effect.resolve(e,tp,eg,ep,ev,re,r,rp)
  local g=Duel.SelectMatchingCard(tp,effect.filter,tp,LOCATION_DECK,0,1,1,nil)
  if #g>0 then
    Duel.SendtoHand(g,nil,REASON_EFFECT)
  end
end
"""
    xyz_script = b"function effect.initial_effect(c)\nend\n"
    checksum = sha256(script).hexdigest()
    xyz_checksum = sha256(xyz_script).hexdigest()
    lua = LuaEffectSource.__new__(LuaEffectSource)
    lua._scripts = {
        **{f"c{cid}.lua": (script, checksum) for cid in (1, 3, 5, 7, 9, 11)},
        "c37.lua": (xyz_script, xyz_checksum),
    }
    lua._binding = dict(
        extractor="synthetic",
        scripts_sha256="b" * 64,
        script_commit="0" * 40,
        core_commit="0" * 40,
        source_lock_sha256="c" * 64,
        card_data_sha256="d" * 64,
    )
    lua._second_codes = ()
    lua._utility = {}
    lua._constants = dict(
        EFFECT_TYPE_ACTIVATE=16, EFFECT_TYPE_QUICK_O=256, EFFECT_TYPE_SINGLE=1,
        EVENT_FREE_CHAIN=1002, EVENT_SUMMON_SUCCESS=1100, EVENT_SPSUMMON_SUCCESS=1102,
        EVENT_FLIP=1001, LOCATION_DECK=1, LOCATION_HAND=2, TYPE_MONSTER=1, REASON_EFFECT=64,
    )
    lua.assert_binding = lambda *args: None
    rules_by_code = {
        cid: [dict(
            scope="card", type=1 | 8 | 128, event=1100, range=0, category=1,
            count_code=cid, count_maximum=1, count_persistent=False,
            callbacks={"target": {"file": f"c{cid}.lua", "sha256": checksum, "lines": [4, 6]},
                       "operation": {"file": f"c{cid}.lua", "sha256": checksum, "lines": [7, 12]}},
        )]
        for cid in (1, 3, 5, 7, 9, 11)
    }
    assets._lua_assets_verified = True
    assets._locked_lua_source = lua
    assets.rule_authority = "locked_period_core"
    assets.period_context = {"period_id": "2022-07"}
    assets.construction_rule_trace = None
    assets.construction_rules = SimpleNamespace(
        frontier_binding=lambda *args: None,
        record_quality=lambda *args: None,
        record_comparison=lambda *args: None,
        evaluate=lambda *args, **kwargs: {"status": "complete", "receipts": [], "pending": []},
    )
    assets.native_registration_source = SimpleNamespace(
        for_cards=lambda codes: {code: dict(diagnostics=[], native=rules_by_code.get(code, [])) for code in codes},
    )

    strong_cards = [1, 1, 1, 3, 3, 3, 5, 5, 5, 7, 7, 7, 9, 9, 9, 11, 11, 11]
    even_fillers = [cid for cid in range(2, 37, 2) for _ in range(3)]
    strong_deck = DeckParts(tuple(sorted(strong_cards + even_fillers[: 40 - len(strong_cards)])), extra=(37,))

    # Below-reference legal deck (full-axis swap keeping only single 0x2c3 card=13 + 39 even fillers -> score=0)
    below_ref_deck = DeckParts(tuple(sorted([13] + even_fillers[:39])), extra=(37,))

    # Hard-constraint-violating deck (zero 0x2c3 cards)
    bad_hard_deck = DeckParts(tuple(sorted(even_fillers[:40])), extra=(37,))

    assets.validate(task, strong_deck)
    assets.validate(task, below_ref_deck)

    tmp_builder = BuildTrainer(
        task,
        assets,
        BuildTrainingConfig(
            model=BuildModelConfig(width=8, card_width=4, heads=2, layers=1, feedforward=16, max_tokens=256),
            batches=1,
        ),
    )
    from ygo_kito.autonomous_construction import initialize_course_vocabulary

    initialize_course_vocabulary(tmp_builder, assets.rows)
    coordinator = CoordinatorTrainer(CoordinatorModelConfig(hidden=4, steps=1))
    tmp_kernel = AutonomousConstructionKernel(
        tmp_builder,
        coordinator,
        assets=assets,
        host_available_ids=assets.rows,
        source_binding={"kind": "synthetic-feedback-test"},
        pool_limit=32,
        candidate_limit=8,
    )
    proposals = tmp_kernel.propose_tasks()
    rank_0x2c3 = next(
        i for i, row in enumerate(proposals["candidates"])
        if row["task"]["goal"]["constraints"][-1]["predicate"] == {"field": "setcode", "value": 0x2c3}
    )
    selection = tmp_kernel.select_task(proposals, rank=rank_0x2c3)
    task = BuildTask.from_dict(selection["task"])
    base_policy, _ = host_construction_quality(task, theme=selection["theme"])
    base_policy["quality"]["theme_rules"] = []
    ref_payload = {
        "reference_id": "synthetic-ref-03",
        "source": "synthetic-feedback-test",
        "environment": deepcopy(task.environment),
        "deck": strong_deck.to_dict(),
    }
    base_policy["pass"] = {
        "mode": "reference_ratio",
        "minimum_reference_ratio": 0.80,
        "reference": {
            "reference_id": "synthetic-ref-03",
            "source": "synthetic-feedback-test",
            "deck_sha256": digest(strong_deck.to_dict()),
        },
    }
    kernel = AutonomousConstructionKernel(
        tmp_builder,
        coordinator,
        assets=assets,
        host_available_ids=assets.rows,
        source_binding={
            "kind": "synthetic-feedback-test",
            "basic_cb_stage": "after_construction",
            "construction_quality_policy": base_policy,
            "construction_quality_reference": ref_payload,
        },
        pool_limit=32,
        candidate_limit=8,
    )
    proposals2 = kernel.propose_tasks()
    rank2 = next(
        i for i, row in enumerate(proposals2["candidates"])
        if row["task"]["goal"]["constraints"][-1]["predicate"] == {"field": "setcode", "value": 0x2c3}
    )
    selection = kernel.select_task(proposals2, rank=rank2)
    return kernel, selection, BuildTask.from_dict(selection["task"]), assets, strong_deck, below_ref_deck, bad_hard_deck


def _mock_candidate_rows(decks, cap=5):
    def _fn(*args, **kwargs):
        from ygo_kito.construction_candidates import changes
        task = args[0]
        base = kwargs.get("base") if "base" in kwargs else (kwargs.get("skeleton") if "skeleton" in kwargs else args[2])
        lim = min(int(kwargs.get("limit", cap)), 5)
        out = []
        for idx, dk in enumerate(decks[:lim]):
            ch = changes(base, dk) if isinstance(base, DeckParts) and len(base.main) == len(dk.main) else ()
            out.append({
                "deck": dk,
                "deck_sha256": digest(dk.to_dict()),
                "strategy": f"synthetic-cand-{idx}",
                "changes": ch,
                "goal_preserved": True,
            })
        return out
    return _fn


class ConstructionFeedbackBoundaryTests(unittest.TestCase):
    def test_initial_reject_then_post_admission_feedback_bypasses_static_scoring(self):
        kernel, selection, task, assets, strong_deck, below_ref_deck, _ = _feedback_fixture()

        def cb_verifier(cand_task, deck, ck_assets, **kwargs):
            return _make_cb_proof(cand_task, deck, ck_assets, success=True)

        # 1. Initial admission on below_ref_deck -> REJECTED at S3-S5 (< 80% reference line), max 5 candidates
        six_cands = [below_ref_deck] * 6
        with (
            patch("ygo_kito.construction_fill._skeleton_candidates", return_value=([below_ref_deck], below_ref_deck)),
            patch("ygo_kito.build_pipeline.goal_candidates", side_effect=_mock_candidate_rows(six_cands, cap=6)),
            patch("ygo_kito.build_pipeline.edit_candidates", side_effect=_mock_candidate_rows(six_cands, cap=6)),
        ):
            init_fail = kernel.run_selected(
                selection,
                base=below_ref_deck,
                basic_cb_enabled=True,
                basic_cb_verifier=cb_verifier,
                run_mode="slice",
                max_iterations=1,
            )
        self.assertFalse(init_fail["construction_passed"])
        self.assertEqual(init_fail["construction_gate"]["status"], "pending")
        self.assertEqual(init_fail["construction_gate"]["outcome"], "failed")
        self.assertIn("quality_pass_line:reference_ratio:failed", init_fail["construction_gate"]["reasons"])
        self.assertLessEqual(init_fail["phases"][-1]["stage_3"]["candidate_count"], 5)
        self.assertLessEqual(len(init_fail["phases"][-1]["stage_3"]["candidate_trace"]["candidates"]), 5)
        self.assertFalse(is_initial_admitted(init_fail["continuation"], task.sha256))

        # CourseAdmissionPolicy + require_training_admission block training admission when below reference line
        course_stub = type("CourseStub", (), {"events": []})()
        cap_policy = CourseAdmissionPolicy(course_stub)
        with patch("ygo_kito.training_admission.verified_conditional_basic_cb", return_value=True):
            denied = require_training_admission(
                task=task,
                deck=below_ref_deck,
                basic_cb={"scope_version": CB_SCOPE_VERSION, "status": "routes_inferred", "inference_completed": True},
                assets=assets,
                purpose="train",
                comparison_policy=lambda **kw: cap_policy(**kw, construction=init_fail),
            )
        self.assertEqual(denied["status"], "deferred")

        # 2. Initial admission with strong_deck -> PASSED S3-S5 and records initial_admission
        kernel2, sel2, task2, assets2, _, _, _ = _feedback_fixture()
        with (
            patch("ygo_kito.construction_fill._skeleton_candidates", return_value=([strong_deck], strong_deck)),
            patch("ygo_kito.build_pipeline.goal_candidates", side_effect=_mock_candidate_rows([strong_deck])),
            patch("ygo_kito.build_pipeline.edit_candidates", side_effect=_mock_candidate_rows([strong_deck])),
        ):
            init_pass = kernel2.run_selected(
                sel2,
                base=strong_deck,
                basic_cb_enabled=True,
                basic_cb_verifier=cb_verifier,
                max_iterations=1,
            )
        self.assertTrue(init_pass["construction_passed"], init_pass.get("stop_reason"))
        self.assertTrue(is_initial_admitted(init_pass["continuation"], task2.sha256))
        self.assertTrue(init_pass["static_gate_passed"])

        # 3. Same legal below_ref_deck (full-axis replacement) submitted via post-admission feedback ->
        # MUST pass feedback_hard_check & targeted CB + duel compare with ZERO static scoring calls!
        duel_calls = []

        def fake_duel_verifier(t, a, active_d, revised_d, *, hard_check=None):
            duel_calls.append((digest(active_d.to_dict()), digest(revised_d.to_dict()), hard_check["static_scoring_calls"]))
            return {
                "kind": "feedback_duel_comparison_v1",
                "adopt": True,
                "status": "complete",
                "active_deck_sha256": digest(active_d.to_dict()),
                "revised_deck_sha256": digest(revised_d.to_dict()),
                "hard_check": hard_check,
                "static_scoring_calls": 0,
            }

        fb_item = {
            "feedback_id": "fb-full-axis-below-ref-1",
            "source": "duel",
            "trigger_kind": "duel",
            "task_sha256": task2.sha256,
            "candidate_sha256": digest(strong_deck.to_dict()),
            "issue": "Targeted axis shift to even-core control after duel loss",
            "revised_deck": below_ref_deck.to_dict(),
        }
        with (
            patch.object(ConstructionLayerAdapter, "evaluate_inventory", side_effect=AssertionError("forbidden static scoring")),
            patch("ygo_kito.construction_quality.evaluate_functional_quality", side_effect=AssertionError("forbidden static scoring")),
            patch("ygo_kito.construction_progress.construction_gate", side_effect=AssertionError("forbidden static scoring")),
        ):
            fb_pass = kernel2.run_selected(
                sel2,
                base=strong_deck,
                optimization_feedback=[fb_item],
                basic_cb_enabled=True,
                basic_cb_verifier=cb_verifier,
                feedback_duel_verifier=fake_duel_verifier,
                max_iterations=1,
            )
            with patch("ygo_kito.training_admission.verified_conditional_basic_cb", return_value=True):
                admitted = require_training_admission(
                    task=task2,
                    deck=below_ref_deck,
                    basic_cb=fb_pass["basic_cb"],
                    assets=assets2,
                    purpose="train",
                    comparison_policy=lambda **kw: cap_policy(**kw, construction=fb_pass),
                )
        self.assertTrue(fb_pass["construction_passed"], fb_pass.get("stop_reason"))
        self.assertEqual(fb_pass["admission_mode"], "feedback_revision")
        self.assertEqual(fb_pass["static_scoring_calls"], 0)
        self.assertEqual(fb_pass["optimizer_learning"]["eligible_strict_pairs"], 0)
        self.assertTrue(fb_pass["feedback_hard_check"]["passed"])
        self.assertEqual(fb_pass["best"]["deck"], below_ref_deck.to_dict())
        self.assertTrue(fb_pass["cb_verified"])
        self.assertEqual(len(duel_calls), 1)
        self.assertEqual(admitted["status"], "admitted")
        self.assertEqual(admitted["admission_mode"], "feedback_revision")
        self.assertEqual(admitted["static_scoring_calls"], 0)

        # JSON round-trip restore_progress preserves initial_admission & feedback_revision state
        from ygo_kito.construction_logic import ConstructionLogic
        s_restore = ConstructionSession("restore feedback", task2)
        orig_session = kernel2.sessions[task2.sha256]
        for ev in orig_session.history:
            if ev.get("stage") == 1:
                s_restore.submit_logic(ConstructionLogic.from_dict(ev["logic"]), role=ev["role"], reason=ev["reason"])
        s_restore.history = deepcopy(orig_session.history)
        restore_payload = json.loads(json.dumps(fb_pass["continuation"]))
        restore_progress(s_restore, restore_payload, assets2)
        self.assertTrue(is_initial_admitted(s_restore.construction_progress, task2.sha256))
        self.assertEqual(s_restore.construction_progress["admission_mode"], "feedback_revision")
        self.assertEqual(s_restore.construction_progress["status"], "passed")

    def test_hard_constraint_violating_feedback_intercepted_before_cb_and_duel(self):
        kernel, selection, task, assets, strong_deck, _, bad_hard_deck = _feedback_fixture()

        def cb_ok(cand_task, deck, ck_assets, **kwargs):
            return _make_cb_proof(cand_task, deck, ck_assets, success=True)

        with (
            patch("ygo_kito.construction_fill._skeleton_candidates", return_value=([strong_deck], strong_deck)),
            patch("ygo_kito.build_pipeline.goal_candidates", side_effect=_mock_candidate_rows([strong_deck])),
            patch("ygo_kito.build_pipeline.edit_candidates", side_effect=_mock_candidate_rows([strong_deck])),
        ):
            init_pass = kernel.run_selected(
                selection,
                base=strong_deck,
                basic_cb_enabled=True,
                basic_cb_verifier=cb_ok,
                max_iterations=1,
            )
        self.assertTrue(init_pass["construction_passed"], init_pass.get("stop_reason"))

        bad_fb = {
            "feedback_id": "fb-invalid-hard-constraint",
            "source": "coordinator",
            "trigger_kind": "duel",
            "task_sha256": task.sha256,
            "candidate_sha256": digest(strong_deck.to_dict()),
            "issue": "Removes all theme cards violating minimum=1",
            "revised_deck": bad_hard_deck.to_dict(),
        }
        with (
            patch.object(ConstructionLayerAdapter, "evaluate_inventory", side_effect=AssertionError("static scoring forbidden")),
            patch("ygo_kito.construction_quality.evaluate_functional_quality", side_effect=AssertionError("static scoring forbidden")),
            patch("ygo_kito.construction_progress.construction_gate", side_effect=AssertionError("static scoring forbidden")),
            patch("ygo_kito.course_admission_policy.InventoryDependencies", side_effect=AssertionError("inventory dependencies forbidden")),
        ):
            def forbidden_cb(*args, **kwargs):
                raise AssertionError("CB verifier must NOT be called before hard check passes")

            def forbidden_duel(*args, **kwargs):
                raise AssertionError("Duel verifier must NOT be called before hard check passes")

            blocked = kernel.run_selected(
                selection,
                base=strong_deck,
                optimization_feedback=[bad_fb],
                basic_cb_enabled=True,
                basic_cb_verifier=forbidden_cb,
                feedback_duel_verifier=forbidden_duel,
                max_iterations=1,
            )
            course_stub = type("CourseStub", (), {"events": []})()
            cap_policy = CourseAdmissionPolicy(course_stub)
            verdict = cap_policy.record_completed_construction(
                task=task,
                deck=bad_hard_deck,
                assets=assets,
                basic_cb={"status": "not_run"},
                cycle_id="fb-invalid",
                construction=blocked,
            )
        self.assertFalse(blocked["construction_passed"])
        self.assertEqual(blocked["stop_reason"], "feedback_hard_check_failed")
        self.assertFalse(blocked["feedback_hard_check"]["passed"])
        self.assertEqual(blocked["static_scoring_calls"], 0)
        self.assertEqual(blocked["construction_candidate"]["deck"], strong_deck.to_dict())
        self.assertTrue(verdict["force_optimization"])
        self.assertEqual(verdict["static_scoring_calls"], 0)

    def test_scenario_course_revise_deck_from_feedback_and_compare_feedback_revision(self):
        kernel, selection, task, assets, strong_deck, below_ref_deck, _ = _feedback_fixture()

        def cb_ok(cand_task, deck, ck_assets, **kwargs):
            return _make_cb_proof(cand_task, deck, ck_assets, success=True)

        with (
            patch("ygo_kito.construction_fill._skeleton_candidates", return_value=([strong_deck], strong_deck)),
            patch("ygo_kito.build_pipeline.goal_candidates", side_effect=_mock_candidate_rows([strong_deck])),
            patch("ygo_kito.build_pipeline.edit_candidates", side_effect=_mock_candidate_rows([strong_deck])),
        ):
            init_pass = kernel.run_selected(
                selection,
                base=strong_deck,
                basic_cb_enabled=True,
                basic_cb_verifier=cb_ok,
                max_iterations=1,
            )
        self.assertTrue(init_pass["construction_passed"], init_pass.get("stop_reason"))

        with (
            patch.object(ConstructionLayerAdapter, "evaluate_inventory", side_effect=AssertionError("static scoring forbidden")),
            patch("ygo_kito.build_feedback.compare_candidates", return_value=(
                {"preferred_index": 1, "status": "complete", "mean_scores": [0.2, 0.8]},
                [{"game": 0}],
            )) as cmp_mock,
        ):
            cmp_res = compare_feedback_revision(
                task, assets, strong_deck, below_ref_deck, strong_deck,
                seeds=(7, 24), purpose="construction_validation", seconds=30.0,
            )
        self.assertTrue(cmp_res["adopt"])
        self.assertEqual(cmp_res["static_scoring_calls"], 0)
        cmp_mock.assert_called_once()

        # Authentic cross-restart JSON checkpoint recovery via kernel.state_dict() / kernel.load_state_dict()
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_kernel = json.loads(json.dumps(kernel.state_dict()))
            kernel.sessions.clear()
            kernel.load_state_dict(saved_kernel)

            course = ScenarioCourse.__new__(ScenarioCourse)
            models_stub = type("Models", (), {
                "kernel": kernel,
                "models": lambda self: {"builder": kernel.builder.models["build_optimizer"]},
                "rng_state": lambda self: {},
                "restore_rng": lambda self, st: None,
                "fingerprint": lambda self: {"builder": "fixed"},
            })()
            course.models = models_stub
            course.assets = assets
            course.bots = {"val-0": {"stage": "bots-bo1", "purpose": "validation", "deck": strong_deck}}
            course.deck = strong_deck
            course.selection = selection
            course.construction = deepcopy(init_pass)
            course.rules = type("Rules", (), {"validate": lambda self, d: assets.validate(task, d)})()
            course.events = []
            course.root = Path(tmpdir)
            course.save = lambda: None
            course.stage = lambda: "bots-bo1"

            fb = {
                "feedback_id": "fb-course-adopt",
                "source": "duel",
                "trigger_kind": "duel",
                "task_sha256": task.sha256,
                "candidate_sha256": digest(strong_deck.to_dict()),
                "issue": "Course validation duel prefers revised deck",
                "revised_deck": below_ref_deck.to_dict(),
            }
            with (
                patch.object(ConstructionLayerAdapter, "evaluate_inventory", side_effect=AssertionError("static scoring forbidden")),
                patch("ygo_kito.construction_quality.evaluate_functional_quality", side_effect=AssertionError("static scoring forbidden")),
                patch("ygo_kito.construction_progress.construction_gate", side_effect=AssertionError("static scoring forbidden")),
                patch("ygo_kito.build_feedback.compare_candidates", return_value=(
                    {"preferred_index": 1, "status": "complete", "mean_scores": [0.3, 0.7]},
                    [{"game": 0}],
                )),
            ):
                adopted_res = course.revise_deck_from_feedback(
                    fb, basic_cb_enabled=True, basic_cb_verifier=cb_ok,
                )
            self.assertTrue(adopted_res["adopted"])
            self.assertEqual(adopted_res["static_scoring_calls"], 0)
            self.assertEqual(course.deck, below_ref_deck)

            fb_reject = {
                "feedback_id": "fb-course-reject",
                "source": "duel",
                "trigger_kind": "duel",
                "task_sha256": task.sha256,
                "candidate_sha256": digest(below_ref_deck.to_dict()),
                "issue": "Candidate revision loses validation duel",
                "revised_deck": strong_deck.to_dict(),
            }
            with (
                patch.object(ConstructionLayerAdapter, "evaluate_inventory", side_effect=AssertionError("static scoring forbidden")),
                patch("ygo_kito.construction_quality.evaluate_functional_quality", side_effect=AssertionError("static scoring forbidden")),
                patch("ygo_kito.construction_progress.construction_gate", side_effect=AssertionError("static scoring forbidden")),
                patch("ygo_kito.build_feedback.compare_candidates", return_value=(
                    {"preferred_index": 0, "status": "complete", "mean_scores": [0.8, 0.2]},
                    [{"game": 0}],
                )),
            ):
                rejected_res = course.revise_deck_from_feedback(
                    fb_reject, basic_cb_enabled=True, basic_cb_verifier=cb_ok,
                )
            self.assertFalse(rejected_res["adopted"])
            self.assertEqual(rejected_res["stop_reason"], "feedback_duel_not_adopted")
            self.assertEqual(course.deck, below_ref_deck)
            pending = rejected_res["result"]["continuation"]
            self.assertEqual(pending["handoffs"][-1]["output_deck_sha256"], digest(course.deck.to_dict()))
            self.assertEqual(pending["pending_duel_revision"]["candidate"]["deck"], strong_deck.to_dict())
            kernel.load_state_dict(json.loads(json.dumps(kernel.state_dict())))
            with patch.object(ConstructionLayerAdapter, "evaluate_inventory", side_effect=AssertionError("static scoring")):
                course.bots = {}
                deferred = course.revise_deck_from_feedback([], basic_cb_verifier=cb_ok)
                self.assertFalse(deferred["adopted"])
                self.assertEqual(deferred["stop_reason"], "feedback_duel_comparison_pending")
                self.assertEqual(course.deck, below_ref_deck)
                kernel.load_state_dict(json.loads(json.dumps(kernel.state_dict())))
                course.bots["val-0"] = dict(stage="bots-bo1", purpose="validation", deck=strong_deck)
                with patch("ygo_kito.build_feedback.compare_candidates", return_value=(
                    {"preferred_index": 1, "status": "engineering_preference_observed"}, [])):
                    resumed = course.revise_deck_from_feedback([], basic_cb_verifier=cb_ok)
                self.assertTrue(resumed["adopted"])
                self.assertEqual(resumed["static_scoring_calls"], 0)
                self.assertEqual(course.deck, strong_deck)
                self.assertNotIn("pending_duel_revision", resumed["result"]["continuation"])


if __name__ == "__main__":
    unittest.main()
