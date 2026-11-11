"""Environment branches tested only with artificial data and temporary files."""
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
import torch

from tests.test_multifactor_training_controls_v3 import make
from tests.test_multifactor_learning_v3 import build,runner_module,binding,PROTOCOL
from tests.test_multifactor_service import facts,request,published
from tests.multifactor_helpers import task_temporary_directory
from ygo_kito.multifactor import RoleAnalyzer,DeckSpec
from ygo_kito.multifactor.contracts import FactorContractError,digest
from ygo_kito.multifactor.environment import (EnvironmentAdapter,EnvironmentConfig,EnvironmentProvider,FEATURES,
    fit_environment_calibration,assess_environment)


def context():
    return dict(environment_id="artificial-environment",period="fixture-period",driver_version="fixture-driver",
                features={k:.4 for k in FEATURES})


def source():
    return dict(kind="engineering_fixture",partition="train",group="training-fixture",evidence_ref="artificial",confidence=1.)


class EnvironmentTests(unittest.TestCase):
    def test_three_modes_update_independently_and_preserve_base(self):
        base=make(); before={k:v.clone() for k,v in base.model.state_dict().items()}
        for mode in ("head_only","lora_head","full_copy"):
            with self.subTest(mode=mode):
                adapter=base.create_environment_adapter(EnvironmentConfig(mode=mode,learning_rate=.0001 if mode=="full_copy" else .001),engineering_mode=True)
                old=adapter.predict([build()],[context()])[0]
                adapter.train([build()],[context()],[1.],[source()])
                self.assertNotEqual(old,adapter.predict([build()],[context()])[0])
                self.assertEqual(adapter.status()["status"],"engineering_only")
                if mode=="head_only": self.assertFalse(any(p.requires_grad for p in adapter.encoder.parameters()))
                if mode=="lora_head":
                    self.assertTrue(any("delta." in n and p.requires_grad for n,p in adapter.encoder.named_parameters()))
                    self.assertFalse(any("delta." not in n and p.requires_grad for n,p in adapter.encoder.named_parameters()))
        for name,value in base.model.state_dict().items():
            torch.testing.assert_close(value,before[name],rtol=0,atol=0)
        self.assertEqual(base.steps,0)

    def test_resume_all_modes_matches_next_update(self):
        base=make()
        with task_temporary_directory() as root:
            for mode in ("head_only","lora_head","full_copy"):
                with self.subTest(mode=mode):
                    a=EnvironmentAdapter(base,EnvironmentConfig(mode=mode),engineering_mode=True)
                    a.train([build()],[context()],[1.],[source()],data_cursor="next")
                    path=Path(root)/(mode+".pt"); a.save(path)
                    b=EnvironmentAdapter.load(base,path)
                    self.assertEqual(b.data_cursor,"next")
                    for adapter in (a,b): adapter.train([build()],[context()],[0.],[source()])
                    self.assertEqual(a.identity(),b.identity())
                    self.assertEqual(a.predict([build()],[context()]),b.predict([build()],[context()]))
                    with self.assertRaises(FactorContractError): a.save(path)

    def test_wrong_base_source_and_hidden_feature_are_rejected(self):
        base=make();a=EnvironmentAdapter(base,engineering_mode=True)
        with self.assertRaises(FactorContractError):
            a.train([build()],[context()],[1.],[dict(source(),partition="test")])
        with self.assertRaises(FactorContractError):
            a.train([build()],[context()],[1.],[dict(source(),kind="environment_feedback")])
        bad=context();bad["features"]["opponent_hidden_hand"]=1.
        with self.assertRaises(FactorContractError): a.predict([build()],[bad])
        with torch.no_grad(): next(base.model.parameters()).add_(.1)
        with self.assertRaises(FactorContractError): a.predict([build()],[context()])

    def test_zero_confidence_feedback_consumes_cursor_without_update(self):
        a=EnvironmentAdapter(make(),engineering_mode=True)
        result=a.train([build()],[context()],[1.],[dict(source(),confidence=0.)],data_cursor="next-fixture")
        self.assertTrue(result["skipped"])
        self.assertEqual(a.data_cursor,"next-fixture")
        self.assertEqual(a.steps,0)

    def test_environment_calibration_isolation_and_engineering_cannot_enable(self):
        rows=[dict(record_id=str(i),group="cal"+str(i),partition="validation",kind="engineering_fixture",
                   evidence_ref="fixture",prediction=x,value=x) for i,x in enumerate((.1,.9))]
        cal=fit_environment_calibration(rows,adapter_id="a",base_id="b",training_groups=["train"])
        final=[dict(r,partition="test",group="final"+r["group"],final_eval_eligible=True,previously_consumed=False) for r in rows]
        assessed=assess_environment(final,cal,baseline_predictions={r["record_id"]:r["prediction"] for r in final},evidence_ref="fixture")
        self.assertAlmostEqual(assessed["calibrated_mse"],0.)
        self.assertFalse(assessed["validated"])
        with self.assertRaises(FactorContractError): fit_environment_calibration(rows,adapter_id="a",base_id="b",training_groups=["cal0"])
        adapter=EnvironmentAdapter(make(),engineering_mode=True)
        with self.assertRaises(FactorContractError): EnvironmentProvider(adapter,lambda _:context(),assessed)

    def test_service_default_off_observe_assist_and_local_failure(self):
        deck=DeckSpec(((1,1),),(),())
        self.assertEqual(RoleAnalyzer(facts,capabilities={"environment_value":published()}).analyze_deck(deck,request()).capabilities["environment_value"]["status"],"disabled")
        provider=Mock();provider.capability=published()
        provider.evaluate.return_value=dict(raw=.4,calibrated=.6,value=.6,environment_id="fixture",
            producer=provider.capability.producer,version=provider.capability.version)
        analyzer=RoleAnalyzer(facts,environment_provider=provider)
        analyzer.analyze_deck(deck,request(mode="off"));provider.evaluate.assert_not_called()
        observed=analyzer.analyze_deck(deck,request(mode="observe"))
        self.assertEqual(observed.genericity["environment_value"]["status"],"unknown")
        result=analyzer.analyze_deck(deck,request(mode="assist"))
        self.assertEqual(result.genericity["environment_value"]["status"],"known")
        provider.evaluate.side_effect=RuntimeError("fixture failure")
        failed=analyzer.analyze_deck(deck,request(mode="assist"))
        self.assertEqual(failed.capabilities["environment_value"]["status"],"failed")
        self.assertTrue(failed.functions)

    def test_environment_runner_fixture_resume_and_pause(self):
        with task_temporary_directory() as root,runner_module():
            run=importlib.import_module("environment_v3");root=Path(root)
            with self.assertRaises(FactorContractError): run.fit(dict(formal_training=False))
            base=make();checkpoint=root/"base.pt";base.save(checkpoint)
            data=root/"feedback.json"
            data.write_text(json.dumps(dict(version="axis-environment-feedback-v3",records=[
                dict(record_id="fixture",observations=build().to_dict()["observations"],environment=context(),value=1.,source=source())])),encoding="utf-8")
            recipe=dict(execution_mode="engineering_fixture",formal_training=False,automatic_lora=False,core_course_resumed=False,
                max_records=1,epochs=1,batch_size=1,run_dir=str(root/"run"),records_file=str(data),
                base=dict(checkpoint=str(checkpoint),network=base.model.config_dict(),binding=binding(),label_protocol_sha256=digest(PROTOCOL),device="cpu"),
                adapter=asdict(EnvironmentConfig()))
            result=run.fit(recipe)
            self.assertEqual(result["steps"],1);self.assertFalse(result["formal_training"])
            resumed=run.fit(dict(recipe,load_mode="resume",adapter_checkpoint=result["adapter_checkpoint"]))
            self.assertEqual(resumed["steps"],1)
            self.assertEqual(resumed["adapter_id"],result["adapter_id"])

    def test_environment_checkpoint_rejects_corrupted_optimizer_and_frozen_base(self):
        base=make();adapter=EnvironmentAdapter(base,EnvironmentConfig(mode="head_only"),engineering_mode=True)
        adapter.train([build()],[context()],[1.],[source()])
        with task_temporary_directory() as root:
            path=Path(root)/"base.pt";adapter.save(path)
            value=torch.load(path,weights_only=True)
            bad=deepcopy(value);next(iter(bad["encoder"].values())).add_(.2)
            corrupt=Path(root)/"corrupt.pt";torch.save(bad,corrupt)
            with self.assertRaises(FactorContractError): EnvironmentAdapter.load(base,corrupt)
            bad=deepcopy(value);next(iter(bad["optimizer"]["state"].values()))["step"]=torch.tensor(float("nan"))
            corrupt2=Path(root)/"corrupt2.pt";torch.save(bad,corrupt2)
            with self.assertRaises(FactorContractError): EnvironmentAdapter.load(base,corrupt2)
