"""Artificial saved-prediction workflow and publication contract checks."""
from copy import deepcopy
import importlib
import gzip
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.test_multifactor_learning_v3 import record,runner_module
from tests.test_multifactor_training_controls_v3 import make
from tests.multifactor_helpers import task_temporary_directory
from ygo_kito.multifactor.calibration import Calibration,fit_calibration,model_identity,host_capabilities,prediction_bundle
from ygo_kito.multifactor.contracts import FactorContractError,digest
from ygo_kito.multifactor.task_queries import query_key,BINARY_COORDINATES
from ygo_kito.multifactor.scoring import CandidateScorer


def rows(fold="validation",prefix="cal",full=False):
    result=[]; predictions={}
    for i,y in enumerate((0,1,0,1)):
        row=record([("mechanism",("card:1",),"search",y)],name=prefix+str(i),kind="engineering_fixture")
        row["supervision"].update(partition=fold,trainable=False)
        row["provenance"].update(leakage_group=prefix+str(i//2),final_eval_eligible=True,previously_consumed=False)
        key=query_key("mechanism",("card:1",),"search")
        result.append(row)
        p=.1 if y==0 else .9
        predictions[row["record_id"]]=dict(raw={key:p},probabilities={key:p},axes={"raw":[]})
        if full:
            label=row["targets"]["task_labels"][0]
            template=deepcopy(label["cells"]["search"])
            label["cells"]={c:deepcopy(template) for c in BINARY_COORDINATES["mechanism"]}
            probabilities={query_key("mechanism",("card:1",),c):p for c in BINARY_COORDINATES["mechanism"]}
            predictions[row["record_id"]].update(raw=probabilities.copy(),probabilities=probabilities)
            original_sources=row["supervision"]["cell_sources"][key]
            for coordinate in BINARY_COORDINATES["mechanism"]:
                row["supervision"]["cell_sources"][query_key("mechanism",("card:1",),coordinate)]=deepcopy(original_sources)
    return result,predictions


def fitted(model_id="fixture-model",full=False):
    records,predictions=rows(full=full)
    return fit_calibration(records,predictions,model_id=model_id,dataset_id="fixture-data",
        selection_groups=["selection"],reserved_groups=["cal0","cal1"],training_groups=["train"])


class WorkflowTests(unittest.TestCase):
    def test_four_cells_and_promotion_preserve_dataset_budget(self):
        with runner_module():
            workflow=importlib.import_module("workflow_v3")
            base=dict(seed=1,network={},dataset_dir="fixture",run_dir="new",epochs=20,effective_batch_size=64,formal_training=False)
            plans=workflow.ablation_recipes(base)
            self.assertEqual(len(plans),4)
            self.assertEqual({(p["config"]["network"]["stream_mode"],p["config"]["network"]["use_route_features"]) for p in plans},
                             {("single",False),("single",True),("dual",False),("dual",True)})
            self.assertTrue(all(p["config"]["formal_training"] is False and p["config"]["epochs"]==20 for p in plans))
            self.assertEqual(len(workflow.ablation_recipes(base,selected=["single-route0","dual-route1"],seeds=[1,2,3])),6)
            with self.assertRaises(FactorContractError):
                workflow.ablation_recipes(base,selected=["dual-route1"],seeds=[1,2,3])

    def test_fit_roundtrip_and_source_isolation(self):
        cal=fitted()
        self.assertEqual(cal.artifact["tasks"]["mechanism"]["status"],"fitted")
        self.assertEqual(cal.artifact["tasks"]["transferability"]["status"],"uncovered")
        with task_temporary_directory() as root:
            path=Path(root)/"cal.json"; cal.save(path)
            self.assertEqual(Calibration.load(path).artifact,cal.artifact)
            with self.assertRaises(FileExistsError): cal.save(path)
        records,predictions=rows()
        for kwargs in (dict(selection_groups=["cal0"]),dict(reserved_groups=["cal0"]),dict(minimum_groups=0)):
            params=dict(model_id="m",dataset_id="d",selection_groups=["s"],reserved_groups=["cal0","cal1"],training_groups=["train"]);params.update(kwargs)
            with self.assertRaises(FactorContractError):
                fit_calibration(records,predictions,**params)
        records[0]["supervision"]["partition"]="test"
        with self.assertRaises(FactorContractError):
            fit_calibration(records,predictions,model_id="m",dataset_id="d",selection_groups=["s"],reserved_groups=["cal0","cal1"],training_groups=["train"])

    def test_three_layers_retain_raw_and_unknown_heads(self):
        records,predictions=rows("test","final")
        before=deepcopy(predictions)
        with runner_module() as runner:
            workflow=importlib.import_module("workflow_v3")
            protocol=runner.read(runner.ROOT/"ASSESSMENT_PROTOCOL.v3.json")
            protocol["bootstrap"]["repetitions"]=5
            report,saved=workflow.evaluate(records,predictions,fitted(),protocol,training_groups=["train"])
        self.assertEqual(predictions,before)
        for rid in predictions:
            self.assertEqual(saved[rid]["raw"],predictions[rid]["raw"])
            self.assertTrue(saved[rid]["calibrated"])
            self.assertTrue(saved[rid]["applied"])
        self.assertEqual(report["partitions"]["test"]["layers"]["applied"]["tasks"]["mechanism"]["coverage"],1)
        self.assertFalse(report["partitions"]["test"]["layers"]["applied"]["tasks"]["transferability"]["complete_class_coverage"])
        self.assertTrue(report["engineering_only"])

    def test_final_overlap_and_retrospective_cannot_publish(self):
        with runner_module() as runner:
            w=importlib.import_module("workflow_v3");cal=fitted()
            protocol=runner.read(runner.ROOT/"ASSESSMENT_PROTOCOL.v3.json");protocol["bootstrap"]["repetitions"]=0
            records,predictions=rows("test","final")
            with self.assertRaises(FactorContractError):
                w.evaluate(records,predictions,cal,protocol,training_groups=["final0"])
            records[0]["provenance"]["previously_consumed"]=True
            report,_=w.evaluate(records,predictions,cal,protocol)
            release=w.release_candidate(report,cal,requested_tasks=["mechanism","transferability"],baseline=report)
            self.assertFalse(any(v["eligible"] for v in release["capabilities"].values()))
            self.assertIn("INDEPENDENT_FINAL_REQUIRED",release["capabilities"]["mechanism"]["reasons"])
            self.assertIn("ENGINEERING_EVIDENCE_ONLY",release["capabilities"]["mechanism"]["reasons"])

    def test_model_binding_detects_post_calibration_updates(self):
        trainer=make();cal=fitted(model_identity(trainer))
        CandidateScorer(trainer,calibrator=cal)
        trainer.train_supervised([record([("mechanism",("card:1",),"search",1)])])
        with self.assertRaises(FactorContractError): CandidateScorer(trainer,calibrator=cal)

    def test_positive_release_decision_is_simulated_and_host_explicit(self):
        trainer=make();cal=fitted(model_identity(trainer),full=True)
        # Simulate a reviewed real evidence envelope to test decision logic only.
        artifact=deepcopy(cal.artifact);artifact.update(source_kinds=["human_feedback"],engineering_only=False)
        cal=Calibration(artifact)
        records,predictions=rows("test","final",full=True)
        for row in records:
            row["supervision"]["source_kinds"]=["human_feedback"]
            for sources in row["supervision"]["cell_sources"].values():
                for source in sources:source["kind"]="human_feedback"
        predictions=prediction_bundle(predictions,records,model_id=cal.artifact["model_id"],dataset_id=cal.artifact["dataset_id"])
        with runner_module() as runner:
            w=importlib.import_module("workflow_v3")
            protocol=runner.read(runner.ROOT/"ASSESSMENT_PROTOCOL.v3.json");protocol["bootstrap"]["repetitions"]=0
            report,_=w.evaluate(records,predictions,cal,protocol)
            baseline=dict(report,model_id="simulated-previous-model")
            release=w.release_candidate(report,cal,requested_tasks=["mechanism"],baseline=baseline)
        self.assertTrue(release["capabilities"]["mechanism"]["eligible"])
        self.assertFalse(release["active_pointer_changed"])
        with self.assertRaises(FactorContractError):
            host_capabilities(release,cal,trainer,evidence_ref="simulated-contract")
        with patch.object(trainer,"head_status",return_value="trained_uncalibrated"):
            caps=host_capabilities(release,cal,trainer,evidence_ref="simulated-contract",assessment_report=report,baseline_report=baseline)
            changed=deepcopy(release);changed["capabilities"]["mechanism"]["reasons"]=["changed"]
            with self.assertRaises(FactorContractError):
                host_capabilities(changed,cal,trainer,evidence_ref="simulated-contract",assessment_report=report,baseline_report=baseline)
        self.assertTrue(caps["mechanism"].assist_available)
        self.assertEqual(trainer.steps,0)

    def test_partial_output_coordinate_coverage_cannot_publish_whole_head(self):
        with runner_module() as runner:
            w=importlib.import_module("workflow_v3");cal=fitted()
            records,predictions=rows("test","final")
            protocol=runner.read(runner.ROOT/"ASSESSMENT_PROTOCOL.v3.json");protocol["bootstrap"]["repetitions"]=0
            report,_=w.evaluate(records,predictions,cal,protocol)
            release=w.release_candidate(report,cal,requested_tasks=["mechanism"],baseline=report)
            self.assertIn("CALIBRATION_COORDINATES_UNCOVERED",release["capabilities"]["mechanism"]["reasons"])
            self.assertIn("APPLIED_COORDINATES_UNCOVERED",release["capabilities"]["mechanism"]["reasons"])

    def test_ablation_comparison_refuses_different_budget_or_seeds(self):
        with runner_module():
            w=importlib.import_module("workflow_v3")
            identity=dict(dataset="d",split="s",epochs=20,effective_batch_size=64,optimizer="adamw",selection_groups=["s"])
            a=dict(cell="single-route0",seed=1,score=.8,scope="development",comparison_binding=identity)
            b=dict(a,cell="dual-route0",score=.9)
            self.assertEqual(len(w.compare_ablation([a,b])["cells"]),2)
            with self.assertRaises(FactorContractError): w.compare_ablation([a,dict(b,seed=2)])
            with self.assertRaises(FactorContractError): w.compare_ablation([a,dict(b,scope="test")])

    def test_predict_saved_includes_probabilities_for_calibration(self):
        trainer=make(); records,_=rows()
        with runner_module() as runner:
            saved=runner.predict_saved(trainer,records)
        for value in saved.values():
            self.assertTrue(value["probabilities"])
            self.assertIn("axis_probabilities",value)

    def test_categorical_calibration_keeps_probabilities_and_rejects_missing_class(self):
        records=[];predictions={}
        labels=("open","conditional","closed")
        for i,label in enumerate(labels*2):
            row=record([("transferability",("query:unit",),"portability",label)],name="cat"+str(i),kind="engineering_fixture")
            row["supervision"].update(partition="validation",trainable=False)
            row["provenance"]["leakage_group"]="cat"+str(i//3)
            key=query_key("transferability",("query:unit",),"portability")
            probabilities={c:.8 if c==label else .1 for c in labels}
            records.append(row);predictions[row["record_id"]]=dict(probabilities={key:probabilities},raw={key:label})
        cal=fit_calibration(records,predictions,model_id="m",dataset_id="d",selection_groups=["s"],reserved_groups=["cat0","cat1"],training_groups=["train"])
        self.assertEqual(cal.artifact["tasks"]["transferability"]["status"],"fitted")
        output=cal("transferability",(dict(task="transferability",subject=["query:unit"],coordinate="portability",value={"open":.8,"conditional":.1,"closed":.1}),))
        self.assertAlmostEqual(sum(output["calibrated_scores"][0]["value"].values()),1.)
        self.assertEqual(output["applied_prediction"][0]["value"],"open")

    def test_source_balance_does_not_count_many_variants_as_independent(self):
        with runner_module():
            w=importlib.import_module("workflow_v3")
            records,predictions=rows("test","final")
            key=query_key("mechanism",("card:1",),"search")
            for row in records[:2]: predictions[row["record_id"]]["raw"][key]=1.-predictions[row["record_id"]]["raw"][key]
            first=w.source_balanced(records,predictions,"raw")["mechanism"]
            for i in range(30):
                row=deepcopy(records[2+i%2]);row["record_id"]="variant"+str(i)
                predictions[row["record_id"]]=deepcopy(predictions[records[2+i%2]["record_id"]]);records.append(row)
            second=w.source_balanced(records,predictions,"raw")["mechanism"]
            self.assertAlmostEqual(first["per_coordinate"]["search"]["f1"],second["per_coordinate"]["search"]["f1"])

    def test_cli_saved_calibration_evaluation_release_roundtrip(self):
        import sys
        with task_temporary_directory() as root,runner_module() as runner:
            root=Path(root);w=importlib.import_module("workflow_v3")
            records,predictions=rows()
            def invoke(action,payload,name):
                inp=root/(name+"-input.json");out=root/(name+"-output.json")
                inp.write_text(json.dumps(payload),encoding="utf-8")
                with patch.object(sys,"argv",["workflow_v3",action,"--input",str(inp),"--output",str(out)]):
                    w.main()
                return json.loads(out.read_text("utf-8"))
            cal=invoke("calibrate",dict(records=records,predictions=predictions,model_id="fixture",dataset_id="d",
                selection_groups=["s"],reserved_groups=["cal0","cal1"],training_groups=["train"]),"cal")
            records,predictions=rows("test","final")
            protocol=runner.read(runner.ROOT/"ASSESSMENT_PROTOCOL.v3.json");protocol["bootstrap"]["repetitions"]=0
            evaluated=invoke("evaluate",dict(records=records,predictions=predictions,calibration=cal,protocol=protocol,
                training_groups=["train"]),"eval")
            release=invoke("release-candidate",dict(report=evaluated["report"],calibration=cal,
                requested_tasks=["mechanism"],baseline=evaluated["report"]),"release")
            self.assertFalse(release["capabilities"]["mechanism"]["eligible"])
            self.assertFalse(release["active_pointer_changed"])

    def test_evaluation_shards_verify_fold_groups_and_semantic_content(self):
        records,predictions=rows("test","final")
        with task_temporary_directory() as root,runner_module():
            root=Path(root);w=importlib.import_module("workflow_v3")
            shard=root/"test.gz"
            with gzip.open(shard,"wt",encoding="utf-8") as stream:
                stream.write("".join(json.dumps(r)+"\n" for r in records))
            from prepare_v3 import preparation_implementation
            manifest=dict(version="axis-dataset-v3",preparation_identity=dict(semantic_id="fixture-data",implementation=preparation_implementation()),
                shards=dict(test=[dict(file=shard.name,records=len(records),semantic_records=digest(records))]))
            (root/"dataset.json").write_text(json.dumps(manifest),encoding="utf-8")
            selected,identity=w.evaluation_records(root,"test",groups=["final0"])
            self.assertEqual(len(selected),2);self.assertEqual(identity,"fixture-data")
            with self.assertRaises(FactorContractError):w.evaluation_records(root,"train")
            with self.assertRaises(FactorContractError):w.evaluation_records(root,"test",groups=["missing"])
            manifest["shards"]["test"][0]["semantic_records"]="corrupt"
            (root/"dataset.json").write_text(json.dumps(manifest),encoding="utf-8")
            with self.assertRaises(FactorContractError):w.evaluation_records(root,"test")

    def test_prediction_chunks_more_than_64_records_without_updates(self):
        trainer=make();identity=model_identity(trainer)
        records,_=rows()
        many=[]
        for i in range(65):
            row=deepcopy(records[i%len(records)]);row["record_id"]="large"+str(i);many.append(row)
        with runner_module():
            w=importlib.import_module("workflow_v3")
            saved=w.predict_records(trainer,many,batch_size=32)
        self.assertEqual(set(saved),{r["record_id"] for r in many})
        self.assertEqual(model_identity(trainer),identity)
        self.assertEqual(trainer.steps,0)

    def test_bound_training_groups_cannot_be_omitted_to_bypass_isolation(self):
        records,predictions=rows()
        with self.assertRaises(FactorContractError):
            fit_calibration(records,predictions,model_id="m",dataset_id="d",selection_groups=["s"],
                            reserved_groups=["cal0","cal1"],training_groups=["cal0"])
        with runner_module() as runner:
            w=importlib.import_module("workflow_v3")
            records,predictions=rows("test","final")
            records[0]["provenance"]["leakage_group"]="train"
            protocol=runner.read(runner.ROOT/"ASSESSMENT_PROTOCOL.v3.json")
            with self.assertRaises(FactorContractError):
                w.evaluate(records,predictions,fitted(),protocol)
