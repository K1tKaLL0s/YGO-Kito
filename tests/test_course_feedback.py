"""Tiny actual parameter updates exercise plumbing, never model competence."""
from copy import deepcopy
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from ygo_kito.autonomous_construction import AutonomousConstructionKernel,initialize_course_vocabulary
from ygo_kito.build_contracts import BuildTask,DeckParts,digest
from ygo_kito.build_semantics import preference_value,proof
from ygo_kito.build_training import BuildTrainer,supervision_projection
from ygo_kito.coordinator_model import engineering_examples
from ygo_kito.course_feedback import CourseFeedbackUpdater
from ygo_kito.data_isolation import DataIndex
from ygo_kito.duel_model import parameter_digest
from ygo_kito.lora import AdapterConfig,AdapterSession
from ygo_kito.semantic_training import SOURCE
from ygo_kito.validation import ContractError
from tests.test_autonomous_construction import fixture,deck_for


def prepare(root,*,purpose="train",experiment="feedback-experiment"):
    task,assets,builder,coordinator=fixture(initialize=False)
    raw=task.to_dict()
    raw["goal"]["preferences"]=[{"id":"explicit-race-preference","zones":["main"],
        "predicate":{"field":"race_any","value":1},"weight":1}]
    task=BuildTask.from_dict(raw)
    builder=BuildTrainer(task,assets,builder.config)
    initialize_course_vocabulary(builder,assets.rows)
    decks=[deck_for(task,assets,i) for i in range(10)]
    decks=sorted(decks,key=lambda d:preference_value(task,d,assets))
    worse,better=decks[0],decks[-1]
    assert preference_value(task,worse,assets)<preference_value(task,better,assets)
    data={"source":SOURCE,"purpose":purpose,"task_sha256":task.sha256,
        "goals":[{"deck":better.to_dict(),"label":1.,"source":"pinned_catalog_constraint_check","evidence":proof(task,better,assets)},
            {"deck":DeckParts(better.main[:-1]).to_dict(),"label":0.,"source":"explicit_hard_constraint_failure",
                "evidence":{"status":"hard_constraint_failure","reason":"synthetic short section"}}],
        "pairs":[{"better":better.to_dict(),"worse":worse.to_dict(),
            "better_value":preference_value(task,better,assets),"worse_value":preference_value(task,worse,assets),
            "source":"explicit_user_preference_not_strength","hard_constraints_checked":True}],
        "unknown_routes_used_as_negative":False,"competitive_quality_labels":False,
        "public_effect_receipts":assets.effect_receipts(task)}
    data["supervision_sha256"]=digest(supervision_projection(data))
    index=DataIndex(root)
    dataset=index.freeze({"dataset_id":"feedback-data","experiment_id":experiment,"purpose":purpose,
        "family":"construction","versions":task.environment["versions"],"opponents":[],"task_sha256":task.sha256})
    artifact=index.ingest_construction(dataset["dataset_id"],"feedback-record",task,assets,data,seeds=())
    sessions={}
    for role,model in dict(builder.models,coordinator=coordinator.model).items():
        targets=("head.0",) if role!="coordinator" else ("encoder.0","route_head")
        sessions[role]=AdapterSession(model,AdapterConfig("fixture-"+role,role,targets=targets,rank=1,max_updates=8),
            {"base_version":"fixture-base","feature_version":"synthetic-feedback-test","context_sha256":"c"*64})
    models=SimpleNamespace(builder=builder,coordinator=coordinator,sessions=sessions,binding={"synthetic_fixture":True},kernel=None)
    return task,assets,models,index,artifact


def explicit_examples(artifact):
    context=engineering_examples()["records"][0]["context"]
    rows=[{"context":context,"route_label":"construct","forecast_target":None,"provenance":{
        "dataset_id":artifact["dataset_id"],"record_id":artifact["artifact_id"],"source":"explicit-host-engineering-fixture",
        "evidence_sha256":artifact["payload_sha256"]}}]
    from ygo_kito.coord_contracts import rule_route
    rows[0]["route_label"]=rule_route(context)[0]
    return {"source":"host_logged_supervision_v1","records":rows,"real_win_rate_supervision":False,"sha256":digest(rows)}


class CourseFeedbackTests(unittest.TestCase):
    def test_indexed_task_graph_preferences_update_shared_role_and_kernel_counters(self):
        with tempfile.TemporaryDirectory() as temp:
            _,assets,models,index,artifact=prepare(temp)
            models.kernel=AutonomousConstructionKernel(models.builder,models.coordinator,assets=assets,
                host_available_ids=assets.rows,source_binding={"kind":"synthetic-host-fixture"},pool_limit=32)
            proposals=models.kernel.propose_tasks();selection=models.kernel.select_task(proposals)
            task=BuildTask.from_dict(selection["task"])
            data=deepcopy(artifact["payload"]);data["task_sha256"]=task.sha256
            data["public_effect_receipts"]=assets.effect_receipts(task)
            for row in data["goals"]:
                if row["label"]==1:row["evidence"]=proof(task,DeckParts.from_dict(row["deck"]),assets)
            data["supervision_sha256"]=digest(supervision_projection(data))
            index.freeze({"dataset_id":"selected-data","experiment_id":"feedback-experiment","purpose":"train",
                "family":"construction","versions":task.environment["versions"],"opponents":[],"task_sha256":task.sha256})
            selected_artifact=index.ingest_construction("selected-data","selected-record",task,assets,data,seeds=())
            updater=CourseFeedbackUpdater(models,index,"feedback-experiment")
            a=updater.apply_task_preference("task-choice","selected-record",proposals,selection["candidate_id"])
            b=updater.apply_graph_preference("graph-choice","selected-record",selection,0,role="build_goal")
            self.assertNotEqual(a["before_sha256"],a["after_sha256"])
            self.assertNotEqual(b["before_sha256"],b["after_sha256"])
            self.assertEqual(models.kernel.updates["build_goal"],2)
            self.assertEqual(models.sessions["build_goal"].updates,2)
            self.assertEqual(selected_artifact["purpose"],"train")
            with self.assertRaises(ContractError):updater.apply_task_preference("wrong-task","feedback-record",proposals,selection["candidate_id"])
            self.assertIsNone(updater.pending)

    def test_actual_two_build_role_updates_keep_bases_and_consume_exact_data_once(self):
        with tempfile.TemporaryDirectory() as temp:
            task,_,models,index,artifact=prepare(temp)
            updater=CourseFeedbackUpdater(models,index,"feedback-experiment")
            before={r:parameter_digest(s.model) for r,s in models.sessions.items()}
            result=updater.apply_construction("construction-1",artifact["artifact_id"],task)
            self.assertEqual({r["role"] for r in result},{"build_goal","build_optimizer"})
            for row in result:
                self.assertNotEqual(before[row["role"]],parameter_digest(models.sessions[row["role"]].model))
                self.assertFalse(row["ability_verified"]);self.assertFalse(row["quality_inferred_from_single_duel"])
                self.assertEqual(row["update"]["base_parameter_elements_changed"],0)
                models.sessions[row["role"]].verify_base()
            self.assertEqual(before["coordinator"],parameter_digest(models.coordinator.model))
            with self.assertRaises(ContractError):updater.apply_construction("construction-1",artifact["artifact_id"],task)
            with self.assertRaises(ContractError):updater.apply_construction("renamed-same-content",artifact["artifact_id"],task)
            self.assertEqual([models.sessions[r].updates for r in ("build_goal","build_optimizer")],[1,1])

    def test_actual_coordinator_update_requires_explicit_index_bound_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            _,_,models,index,artifact=prepare(temp)
            updater=CourseFeedbackUpdater(models,index,"feedback-experiment")
            before=parameter_digest(models.coordinator.model)
            result=updater.apply_coordinator("coord-1",artifact["artifact_id"],explicit_examples(artifact))
            self.assertNotEqual(before,parameter_digest(models.coordinator.model))
            self.assertEqual(result["role"],"coordinator")
            self.assertIn("not_calibrated",result["label_source"])
            self.assertFalse(result["quality_inferred_from_single_duel"])
            with self.assertRaises(ContractError):updater.apply_coordinator("synthetic-default",artifact["artifact_id"],engineering_examples())
            changed=explicit_examples(artifact);changed["records"][0]["provenance"]["evidence_sha256"]="d"*64
            changed["sha256"]=digest(changed["records"])
            with self.assertRaises(ContractError):updater.apply_coordinator("wrong-record",artifact["artifact_id"],changed)
            self.assertEqual(models.sessions["coordinator"].updates,1)

    def test_heldout_and_other_experiment_reject_before_loss_or_parameter_update(self):
        for purpose,experiment in (("validation","feedback-experiment"),("final_eval","feedback-experiment"),("train","other-experiment")):
            with self.subTest(purpose=purpose,experiment=experiment),tempfile.TemporaryDirectory() as temp:
                task,_,models,index,artifact=prepare(temp,purpose=purpose,experiment=experiment)
                updater=CourseFeedbackUpdater(models,index,"feedback-experiment")
                before={r:parameter_digest(s.model) for r,s in models.sessions.items()}
                with patch("ygo_kito.course_feedback.construction_loss",side_effect=AssertionError("loss must not run")):
                    with self.assertRaises(ContractError):updater.apply_construction("bad",artifact["artifact_id"],task)
                with self.assertRaises(ContractError):updater.apply_coordinator("bad-coord",artifact["artifact_id"],explicit_examples(artifact))
                self.assertEqual(before,{r:parameter_digest(s.model) for r,s in models.sessions.items()})
                self.assertEqual(updater.consumed,[]);self.assertIsNone(updater.pending)

    def test_consumption_restores_with_exact_models_and_rejects_tamper_or_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            task,_,models,index,artifact=prepare(temp)
            updater=CourseFeedbackUpdater(models,index,"feedback-experiment")
            updater.apply_construction("once",artifact["artifact_id"],task,roles=("build_goal",))
            state=updater.state_dict();restored=CourseFeedbackUpdater(models,index,"feedback-experiment")
            restored.load_state_dict(state)
            self.assertEqual(restored.state_dict(),state)
            with self.assertRaises(ContractError):restored.apply_construction("again",artifact["artifact_id"],task,roles=("build_goal",))
            bad=deepcopy(state);bad["consumed"]=[]
            with self.assertRaises(ContractError):restored.load_state_dict(bad)
            self.assertEqual(restored.state_dict(),state)

    def test_interrupted_update_records_pending_and_refuses_automatic_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            task,_,models,index,artifact=prepare(temp)
            updater=CourseFeedbackUpdater(models,index,"feedback-experiment")
            with patch.object(models.sessions["build_goal"],"step",side_effect=ContractError("fixture interruption before step")):
                with self.assertRaises(ContractError):updater.apply_construction("uncertain",artifact["artifact_id"],task)
            self.assertEqual(updater.pending["outcome"],"failed_or_uncertain_do_not_replay")
            state=updater.state_dict();restored=CourseFeedbackUpdater(models,index,"feedback-experiment")
            restored.load_state_dict(state)
            with self.assertRaises(ContractError):restored.apply_construction("retry",artifact["artifact_id"],task)
            self.assertTrue(all(s.updates==0 for s in models.sessions.values()))


if __name__=="__main__":unittest.main()
