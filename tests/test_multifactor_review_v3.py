"""Design regression cases discovered by the whole-module source review."""
from copy import deepcopy
from dataclasses import asdict,replace
import gzip
import importlib
import json
from pathlib import Path
import random
import sqlite3
import unittest
from unittest.mock import patch

import torch

from tests.multifactor_helpers import task_temporary_directory
from tests.test_multifactor_learning_v3 import record,with_comparison,runner_module,binding,PROTOCOL,config,build
from tests.test_multifactor_training_controls_v3 import make
from ygo_kito.multifactor.contracts import FactorContractError,digest
from ygo_kito.multifactor.training import RoleTrainer
from ygo_kito.multifactor.task_queries import query_key,observation_view


def fixture_run(root):
    data=root/"data";data.mkdir()
    manifest=dict(preparation_identity=dict(semantic_id=digest("review-fixture"),semantic_config=dict(split={})),
        split_version="fixture",grouping=dict(groups=["train","validation"]),shards={})
    for fold in ("train","validation"):
        rows=[]
        for i in range(2):
            row=record([("mechanism",("card:1",),"search",i)],name=fold+str(i),kind="engineering_fixture")
            row["supervision"].update(partition=fold,trainable=fold=="train")
            row["provenance"]["leakage_group"]=fold
            rows.append(row)
        path=data/(fold+".gz")
        with gzip.open(path,"wt",encoding="utf-8") as stream:stream.write("".join(json.dumps(r)+"\n" for r in rows))
        manifest["shards"][fold]=[dict(file=path.name,records=len(rows),semantic_records=digest(rows))]
    recipe=dict(network=asdict(config()),device="cpu",execution_mode="engineering_fixture",engineering_max_records=4,
        formal_training=False,automatic_lora=False,core_course_resumed=False,dataset_dir=str(data),run_dir=str(root/"run"),
        epochs=3,patience=1,minimum_improvement=1.,batch_size=1,effective_batch_size=2,save_every_batches=5,
        seed=17,learning_rate=.001,load_mode="fresh",label_protocol=PROTOCOL,assessment_protocol="ASSESSMENT_PROTOCOL.v3.json",
        selection_tasks=["mechanism"])
    return recipe,manifest


class ReviewTests(unittest.TestCase):
    def test_retired_training_stack_is_absent_and_prepare_import_is_v3(self):
        root=Path(__file__).resolve().parents[1]/"training/axis_generic"
        for name in ("train_base.py","prepare_base.py","prepare_balanced.py","finish_existing.py","features_v4.py","goal_semantics.py","check_scopes.py","config.json","config.train.software.v3.json"):
            self.assertFalse((root/name).exists(),name)
        with runner_module():
            entry=importlib.import_module("prepare_only")
            self.assertEqual(entry.prepare.__module__,"prepare_v3")
            for name in ("train_base","prepare_base","prepare_balanced","features_v4"):
                self.assertIsNone(importlib.util.find_spec(name))

    def test_inference_load_keeps_rng_and_rejects_updates(self):
        a=make();a.train_supervised([record([("mechanism",("card:1",),"search",1)])])
        with task_temporary_directory() as root:
            path=Path(root)/"base.pt";a.save(path)
            payload=torch.load(path,weights_only=True)
            payload["runtime"]["threads"]+=1
            portable=Path(root)/"portable.pt";torch.save(payload,portable)
            python_state=random.getstate();torch_state=torch.get_rng_state().clone()
            b=RoleTrainer.load(portable,mode="inference",expected_config=config(),expected_binding=binding(),expected_label_protocol_sha256=digest(PROTOCOL))
            self.assertEqual(random.getstate(),python_state)
            torch.testing.assert_close(torch.get_rng_state(),torch_state,rtol=0,atol=0)
            self.assertTrue(b.inference_only);self.assertFalse(b.optimizer.state)
            self.assertEqual(a.updates,b.updates)
            with self.assertRaises(FactorContractError):b.train_supervised([record()])
            with self.assertRaises(FactorContractError):b.save(Path(root)/"forbidden.pt")

    def test_zero_evidence_head_is_unchanged_with_adamw_default_path(self):
        row=record([("mechanism",("card:1",),"search",1)])
        other=record([("axis_origin",(record()["observations"]["candidates"]["candidates"][0]["candidate_id"],),"origin","intrinsic")],confidence=0.)
        current=make(optimizer_config=dict(name="adamw",weight_decay=1.))
        before={k:v.clone() for k,v in current.model.state_dict().items() if "heads.axis_origin." in k}
        current.train_supervised([row,other])
        self.assertTrue(before)
        for k,v in before.items():torch.testing.assert_close(v,current.model.state_dict()[k],rtol=0,atol=0)
        self.assertEqual(sum(current.updates["axis_origin"].values()),0)

    def test_resume_after_epoch_checkpoint_obeys_saved_early_stop(self):
        with task_temporary_directory() as temp,runner_module() as runner:
            root=Path(temp);recipe,manifest=fixture_run(root)
            def crash(event,**values):
                if event=="v3_epoch" and values["epoch"]==2:raise RuntimeError("controlled review interruption")
            with self.assertRaisesRegex(RuntimeError,"controlled review interruption"):
                runner.fit(recipe,root/"run",manifest,crash)
            (root/"run/best-development.json").unlink()
            recipe["load_mode"]="resume"
            result=runner.fit(recipe,root/"run",manifest,lambda *a,**kw:None)
            self.assertTrue(result["resumed_completed"]);self.assertEqual(result["updates"],2)
            self.assertEqual(result["stop_reason"],"early_stopping")
            self.assertTrue((root/"run/best-development.json").is_file())

    def test_mutable_json_write_is_not_blocked_by_abandoned_fixed_temp(self):
        with task_temporary_directory() as root,runner_module() as runner:
            path=Path(root)/"latest.json"
            path.with_name("latest.json.tmp").write_text("abandoned",encoding="utf-8")
            runner.write(path,dict(file="new.pt"))
            self.assertEqual(runner.read(path),dict(file="new.pt"))

    def test_single_graph_copy_labels_refuse_before_update(self):
        row=record([("copy_preference",("query:unit","card:3"),"preference","left")])
        current=make()
        with patch.object(current.optimizer,"step",side_effect=AssertionError("must reject first")):
            with self.assertRaises(FactorContractError):current.train_supervised([row])

    def test_paired_preference_batch_matches_service_raw_probabilities(self):
        from ygo_kito.multifactor.scoring import CandidateScorer
        from ygo_kito.multifactor import build_analysis_graph,FunctionSeed
        from ygo_kito.multifactor.task_queries import observation_view
        row=with_comparison(record([("copy_preference",("query:unit","query:unit"),"preference","left")]))
        current=make();current.train_supervised([row],micro_batch_size=1)
        with runner_module() as runner:
            saved=runner.predict_saved(current,[row])
        left_parts=observation_view(row);right_parts=observation_view(row["comparison"]["right"])
        left=build()
        right=build_analysis_graph(right_parts[0],function_seeds=(FunctionSeed('observed-search',(('card:1',1),('card:2',1)),('search',)),))
        scorer=CandidateScorer(current,calibrator=lambda task,raw:dict(calibrated_scores=(),applied_prediction=()))
        with patch.object(current,"head_status",return_value="trained_uncalibrated"):
            output=scorer.score_copy_graphs(left,right,operation=row["comparison"]["operation"])
        key=query_key("copy_preference",("query:unit","query:unit"),"preference")
        self.assertEqual(saved[row["record_id"]]["probabilities"][key],output["raw_prediction"][0]["value"])

    def test_hidden_cell_source_and_wrong_prediction_artifact_refuse(self):
        from tests.test_multifactor_workflow_v3 import rows,fitted
        from ygo_kito.multifactor.calibration import fit_calibration,prediction_bundle
        records,predictions=rows()
        forged=deepcopy(records)
        for row in forged:row["supervision"]["source_kinds"]=["human_feedback"]
        with self.assertRaises(FactorContractError):
            fit_calibration(forged,predictions,model_id="m",dataset_id="d",training_groups=["train"],
                selection_groups=["s"],reserved_groups=["cal0","cal1"])
        artifact=prediction_bundle(predictions,records,model_id="other-model",dataset_id="d")
        with self.assertRaises(FactorContractError):
            fit_calibration(records,artifact,model_id="expected-model",dataset_id="d",training_groups=["train"],
                selection_groups=["s"],reserved_groups=["cal0","cal1"])
        artifact=prediction_bundle(predictions,records,model_id="m",dataset_id="d")
        records[0]["targets"]["task_labels"][0]["cells"]["search"]["value"]=1
        with self.assertRaises(FactorContractError):
            fit_calibration(records,artifact,model_id="m",dataset_id="d",training_groups=["train"],
                selection_groups=["s"],reserved_groups=["cal0","cal1"])

    def test_multilabel_macro_does_not_hide_a_rare_coordinate(self):
        from tests.test_multifactor_workflow_v3 import rows
        from ygo_kito.multifactor.task_queries import BINARY_COORDINATES
        records,predictions=rows("test","final",full=True)
        key=query_key("mechanism",("card:1",),"recycle")
        for row in records:predictions[row["record_id"]]["raw"][key]=1-predictions[row["record_id"]]["raw"][key]
        with runner_module():
            workflow=importlib.import_module("workflow_v3")
            metric=workflow.source_balanced(records,predictions,"raw")["mechanism"]
        self.assertEqual(metric["per_coordinate"]["recycle"]["f1"],0)
        self.assertAlmostEqual(metric["f1"],1-1/len(BINARY_COORDINATES["mechanism"]))

    def test_preference_preparation_preserves_pair_and_right_card_holdout(self):
        from tests.test_multifactor_data_v3 import preparation_modules,config as preparation_config
        from ygo_kito.multifactor.splits import referenced_cards,assign_group_splits
        row=with_comparison(record([("copy_preference",("query:unit","query:unit"),"preference","left")]))
        row.update(schema_version="axis-source-record-v3")
        row["observations"]={"input":row["observations"]["input"]}
        row["comparison"]["right"]={"input":row["comparison"]["right"]["input"]}
        row["supervision"]={"kind":"engineering_fixture"}
        row["provenance"]={"source_namespace":"fixture","final_eval_eligible":True,"previously_consumed":False}
        with preparation_modules() as (preparation,_):
            prepared,report=preparation.prepare_records([row],preparation_config())
        self.assertIn("comparison",prepared[0])
        self.assertIn(4,referenced_cards(row))
        assigned,_=assign_group_splits([row],protocol="unseen_card",heldout_cards=[4],require_three=False)
        self.assertEqual(assigned,["test"])
        current=make()
        current.train_supervised(prepared,micro_batch_size=1)
        self.assertEqual(current.updates["copy_preference"]["engineering_fixture"],1)
        bad=deepcopy(row);bad["comparison"]["operation"]["add"]["quantity"]=2
        with preparation_modules() as (preparation,_):
            with self.assertRaises(FactorContractError):preparation.prepare_records([bad],preparation_config())

    def test_environment_bad_tail_is_validated_before_any_base_load_or_update(self):
        from tests.test_multifactor_environment_v3 import context,source
        with task_temporary_directory() as temp,runner_module():
            root=Path(temp);module=importlib.import_module("environment_v3")
            rows=[dict(record_id="good",observations=build().to_dict()["observations"],environment=context(),value=1.,source=source()),
                  dict(record_id="bad",observations=build().to_dict()["observations"],environment=context(),value=2.,source=source())]
            data=root/"feedback.json";data.write_text(json.dumps(dict(version="axis-environment-feedback-v3",records=rows)),encoding="utf-8")
            recipe=dict(execution_mode="engineering_fixture",formal_training=False,automatic_lora=False,core_course_resumed=False,
                max_records=2,epochs=1,batch_size=1,run_dir=str(root/"run"),records_file=str(data),base=dict(device="cpu"),adapter={})
            with patch.object(RoleTrainer,"load",side_effect=AssertionError("must validate whole input first")):
                with self.assertRaises(FactorContractError):module.fit(recipe)
            self.assertFalse((root/"run").exists())

    def test_real_environment_requires_base_validation_and_finite_calibration(self):
        from ygo_kito.multifactor.environment import EnvironmentAdapter,assess_environment,fit_environment_calibration
        with self.assertRaises(FactorContractError):EnvironmentAdapter(make(),engineering_mode=False)
        rows=[dict(record_id=str(i),group="cal"+str(i),partition="validation",kind="engineering_fixture",evidence_ref="fixture",prediction=x,value=x) for i,x in enumerate((.1,.9))]
        cal=fit_environment_calibration(rows,adapter_id="a",base_id="b",training_groups=["train"])
        cal["slope"]=float("nan")
        final=[dict(r,partition="test",group="f"+r["group"],final_eval_eligible=True,previously_consumed=False) for r in rows]
        with self.assertRaises(FactorContractError):
            assess_environment(final,cal,baseline_predictions={r["record_id"]:r["prediction"] for r in final},evidence_ref="fixture")

    def test_selection_coverage_refuses_before_model_construction(self):
        with task_temporary_directory() as temp,runner_module() as runner:
            root=Path(temp);recipe,manifest=fixture_run(root)
            recipe["selection_tasks"]=["transferability"]
            with patch.object(RoleTrainer,"__init__",side_effect=AssertionError("selection must be checked first")):
                with self.assertRaisesRegex(FactorContractError,"selection preflight"):
                    runner.fit(recipe,root/"run",manifest,lambda *a,**kw:None)
            self.assertFalse((root/"run/experiment.json").exists())

    def test_old_neural_cli_flags_reject_before_reading_input_or_weights(self):
        import contextlib
        import io
        import sys
        from ygo_kito.multifactor import __main__ as entry
        with patch.object(sys,"argv",["multifactor","--input","not-opened.json","--checkpoint","not-loaded.pt"]):
            with patch.object(Path,"read_text",side_effect=AssertionError("retired path must not read")):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as rejected:entry.main()
        self.assertEqual(rejected.exception.code,2)

    def test_complete_checkpoint_predict_calibrate_cli_keeps_bound_artifact(self):
        import sys
        from tests.test_multifactor_workflow_v3 import rows
        from ygo_kito.multifactor.calibration import model_identity
        with task_temporary_directory() as temp,runner_module():
            root=Path(temp);workflow=importlib.import_module("workflow_v3");current=make()
            checkpoint=root/"model.pt";current.save(checkpoint)
            records,_=rows()
            request=dict(evaluation_authorized=True,checkpoint=str(checkpoint),network=current.model.config_dict(),
                binding=binding(),label_protocol_sha256=digest(PROTOCOL),device="cpu",records=records)
            inp=root/"predict.json";out=root/"predictions.json"
            inp.write_text(json.dumps(request),encoding="utf-8")
            with patch.object(sys,"argv",["workflow","predict","--input",str(inp),"--output",str(out)]):workflow.main()
            artifact=json.loads(out.read_text("utf-8"))
            self.assertEqual(artifact["version"],"axis-predictions-v3")
            self.assertEqual(artifact["model_id"],model_identity(current))
            request=dict(records=records,predictions=artifact,model_id=artifact["model_id"],dataset_id=artifact["dataset_id"],
                training_groups=["train"],selection_groups=["s"],reserved_groups=["cal0","cal1"])
            inp=root/"calibrate.json";out=root/"calibration.json";inp.write_text(json.dumps(request),encoding="utf-8")
            with patch.object(sys,"argv",["workflow","calibrate","--input",str(inp),"--output",str(out)]):workflow.main()
            self.assertTrue(json.loads(out.read_text("utf-8"))["engineering_only"])

    def test_readonly_legacy_import_still_works_with_artificial_sqlite_sources(self):
        from tests.test_multifactor_data_v3 import preparation_modules,config as preparation_config
        with task_temporary_directory() as temp,preparation_modules() as (preparation,_):
            root=Path(temp)
            case=dict(case_id="fixture-reference",main=[[1,1]],extra=[],selected_main=[[1,1]],selected_extra=[],
                family="artificial",unit=dict(function_tags=["search"]))
            def write(name,value):
                path=root/name;path.write_text(json.dumps(value),encoding="utf-8");return str(path)
            legacy=dict(cases=write("cases.json",[case]),labels=write("labels.json",[dict(case_id=case["case_id"],roles=[0,0,1,0,1],confidence=[1]*5)]),
                plans=write("plans.json",[dict(case_id=case["case_id"],primary_plan_text="explicit artificial strategy",confidence="high",entities=[])]),
                audit=write("audit.json",[dict(case_id=case["case_id"],core_status="supported",support_status="supported")]),
                generic=write("generic.json",[dict(case_id=case["case_id"],generic_role=1,confidence=.95,condition_scopes=[])]),source_namespace="artificial-migration")
            parent=root/"parent";parent.mkdir()
            with gzip.open(parent/"train.gz","wt",encoding="utf-8") as stream:
                stream.write(json.dumps(dict(reference=case["case_id"],source_rowid=5,variant="complete",labels=[0,0,1,0,1],role_confidence=[1]*5))+"\n")
            (parent/"dataset.json").write_text(json.dumps(dict(shards=dict(train=[dict(file="train.gz")]))),encoding="utf-8")
            legacy.update(parent_dir=str(parent),parent_folds=["train"])
            database=root/"decks.sqlite3";connection=sqlite3.connect(database)
            try:
                connection.execute("create table decks(identity text)")
                connection.execute("insert into decks(rowid,identity) values (?,?)",(5,json.dumps([case["main"],case["extra"]])))
                connection.commit()
            finally:connection.close()
            settings=preparation_config();settings.update(legacy_import=legacy,deck_cache=str(database))
            sources,catalog=preparation.load_sources(settings)
            self.assertEqual(len(sources),2);self.assertEqual(catalog,{})
            self.assertTrue(all(r["provenance"]["previously_consumed"] for r in sources))
            prepared,_=preparation.prepare_records(sources,settings)
            self.assertTrue(prepared)
            self.assertTrue(all(not r["provenance"]["final_eval_eligible"] for r in prepared))
            connection=sqlite3.connect(database)
            try:
                persisted=connection.execute("select rowid,identity from decks").fetchall()
            finally:connection.close()
            self.assertEqual(persisted,[(5,json.dumps([case["main"],case["extra"]]))])

    def test_identical_pair_variant_keeps_reviewed_preference_and_key(self):
        from tests.test_multifactor_data_v3 import preparation_modules,config as preparation_config
        row=with_comparison(record([("copy_preference",("query:unit","query:unit"),"preference","left")]))
        row["schema_version"]="axis-source-record-v3"
        row["observations"]={"input":row["observations"]["input"]}
        row["comparison"]["right"]={"input":row["comparison"]["right"]["input"]}
        row["supervision"]={"kind":"engineering_fixture"}
        row["provenance"]={"source_namespace":"fixture"}
        variant=dict(record_id="same-pair-variant",observations=deepcopy(row["observations"]),comparison=deepcopy(row["comparison"]),
            supervision={"kind":"engineering_fixture"})
        variant["comparison"]["operation"].pop("kind")
        row["variants"]=[variant]
        with preparation_modules() as (preparation,_):
            prepared,report=preparation.prepare_records([row],preparation_config())
        self.assertEqual(len(prepared),1)
        self.assertEqual(prepared[0]["targets"]["task_labels"][0]["cells"]["preference"]["value"],"left")
        self.assertEqual(len(prepared[0]["provenance"]["source_record_ids"]),2)

    def test_unknown_consumption_status_does_not_become_fresh_final(self):
        from tests.test_multifactor_data_v3 import preparation_modules,config as preparation_config,record as source_record
        source=source_record("unknown-history",final_eval_eligible=True,previously_consumed=None)
        source["supervision"]["partition"]="test"
        with preparation_modules() as (preparation,_):
            prepared,report=preparation.prepare_records([source],preparation_config())
        self.assertEqual(prepared[0]["supervision"]["partition"],"retrospective_test")
        self.assertFalse(report["new_independent_final"])

    def test_goal_intent_changes_conditional_heads_only_in_both_stream_modes(self):
        from ygo_kito.multifactor import Factors
        from ygo_kito.multifactor.network import RoleNetwork,encode_batch
        observed=build();axis=observed.candidates.candidates[0].candidate_id
        a=replace(observed,input=replace(observed.input,context=Factors.observed("context",
            {"goal_engine_weight":1.,"goal_interaction_weight":0.,"objective_search":1.},source="explicit engineering goal A")))
        b=replace(observed,input=replace(observed.input,context=Factors.observed("context",
            {"goal_engine_weight":0.,"goal_interaction_weight":1.,"objective_search":0.},source="explicit engineering goal B")))
        intrinsic=[(0,"mechanism",("card:1",),"search"),(0,"axis_membership",(axis,"card:1"),"member"),
            (0,"axis_function",(axis,),"search"),(0,"axis_origin",(axis,),"origin"),
            (0,"transferability",("query:unit","function:search"),"portability"),(0,"legacy:large_axis",("query:unit",),"value")]
        contextual=[(0,"legacy:strategic_core",("query:unit",),"value"),(0,"axis_position",(axis,),"position"),
            (0,"contribution",("query:unit","function:search"),"carrier")]
        for mode in ("single","dual"):
            with self.subTest(mode=mode):
                architecture=config(stream_mode=mode);model=RoleNetwork(architecture).eval()
                batches=[encode_batch([v],config=architecture) for v in (a,b)]
                self.assertFalse(torch.equal(batches[0]["intent"],batches[1]["intent"]))
                outputs=[model(batch) for batch in batches]
                x,y=[model.score_queries(output,batch,intrinsic) for output,batch in zip(outputs,batches)]
                for left,right in zip(x,y):torch.testing.assert_close(left,right,rtol=0,atol=0)
                x,y=[model.score_queries(output,batch,contextual) for output,batch in zip(outputs,batches)]
                self.assertTrue(all(not torch.equal(left,right) for left,right in zip(x,y)))

    def test_old_plan_proxies_and_opaque_goal_names_do_not_enter_intent(self):
        from ygo_kito.multifactor import Factors
        from ygo_kito.multifactor.network import encode_batch
        observed=build()
        a=replace(observed,input=replace(observed.input,context=Factors.observed("context",
            {"plan_known":0.,"plan_reference_coverage":0.,"goal_engine_weight":.7},source="old marker A")))
        b=replace(observed,input=replace(observed.input,context_ref="opaque-renamed-context",context=Factors.observed("context",
            {"plan_known":1.,"plan_reference_coverage":1.,"goal_engine_weight":.7},source="different source B")))
        x,y=[encode_batch([v],config=config()) for v in (a,b)]
        torch.testing.assert_close(x["intent"],y["intent"],rtol=0,atol=0)

    def test_construction_context_provider_delivers_structured_goal_factors(self):
        from ygo_kito.multifactor import Factors,RoleAnalyzer,AnalysisRequestContext,CapabilityStatus
        from ygo_kito.construction_recognition import ConstructionRecognitionProvider
        from tests.test_construction_recognition import fixture
        task,assets,_,_,decks,_=fixture();seen=[]
        class Scorer:
            def score_graph(self,build,**kwargs):
                seen.append(build.input.context.get("goal_engine_weight").value)
                return dict(raw_prediction=(),calibrated_scores=(),applied_prediction=())
        analyzer=RoleAnalyzer(scorer=Scorer(),capabilities={"legacy:strategic_core":CapabilityStatus("trained_uncalibrated")})
        provider=ConstructionRecognitionProvider(analyzer,context_provider=lambda task,deck:AnalysisRequestContext(
            context_ref=task.sha256,declared_goal=json.dumps(task.goal,sort_keys=True,ensure_ascii=False,separators=(",",":")),factors=Factors.observed("context",
                {"goal_engine_weight":.9},source="explicit host intent")))
        provider.analyze_candidate(task,decks[1],assets,mode="observe")
        self.assertEqual(seen,[.9])

    def test_distinct_goals_keep_distinct_supervision_and_intrinsic_pairing(self):
        from ygo_kito.multifactor import Factors
        from tests.test_multifactor_data_v3 import preparation_modules,config as preparation_config
        raw=[]
        for i in (0,1):
            row=record(roles=[None,None,i,None,None],name="goal-"+str(i),kind="engineering_fixture")
            example,_,_=observation_view(row)
            example=replace(example,context=Factors.observed("context",{"goal_engine_weight":float(i)},source="explicit goal counterfactual"))
            row.update(schema_version="axis-source-record-v3",observations={"input":example.to_dict()},
                       supervision={"kind":"engineering_fixture"},provenance={"source_namespace":"goal-fixture"})
            raw.append(row)
        with preparation_modules() as (preparation,_):
            prepared,report=preparation.prepare_records(raw,preparation_config())
        self.assertEqual(len(prepared),2)
        self.assertEqual(len({r["input_key"] for r in prepared}),2)
        self.assertEqual(len({r["provenance"]["leakage_group"] for r in prepared}),1)
        pair=dict(left=0,right=1,task="transferability",subject=["query:unit","function:search"],coordinate="portability",
                  scope="unit_definition",evidence_ref="explicit engineering intrinsic contrast",confidence=1.)
        result=make().train_supervised(prepared,consistency=[pair])
        self.assertAlmostEqual(result["component_losses"]["consistency"],0.)
