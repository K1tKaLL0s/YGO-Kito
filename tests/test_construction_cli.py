"""New CLI contract checks; no resource loading or native-engine execution."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ygo_kito.cli import main
from tests.test_construction_logic import binding, example_graph, fixture_assets, fixture_classifier, text_review
from ygo_kito.build_pipeline import goal_candidates


class ConstructionCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_path = str(self.root / "intent.json")
        fixture_classifier().save(self.model_path)

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def call(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(list(args))
        return code, output.getvalue(), errors.getvalue()

    def test_planning_has_no_torch_or_engine_requirement_and_supports_unknown_themes(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        script = 'import sys; from ygo_kito.cli import main; main(["construction-plan", "--request", "星河织梦主题"]); assert "torch" not in sys.modules'
        result = subprocess.run([sys.executable, "-c", script], env=env, cwd=self.root,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["route"]["stages"], [1])
        self.assertEqual(json.loads(result.stdout)["classification"]["classifier_status"], "untrained")

    def test_plan_graph_roundtrip_and_dictionary_extension_keep_defaults(self):
        graph = example_graph()
        for request, expected in (("星河织梦主题", [1, 2, 3]), ("不要珠泪，只要堆墓", [1, 3]), ("未知裸名", [1])):
            code, out, err = self.call("construction-plan", "--request", request,
                "--logic", self.write("logic.json", graph.to_dict()), "--intent-model", self.model_path)
            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            self.assertEqual(payload["route"]["stages"], expected)
            self.assertEqual(payload["logic_sha256"], graph.sha256)
            self.assertFalse(payload["graph_execution_verified"])

    def test_fill_check_defaults_to_no_engine_validation(self):
        from dataclasses import asdict
        task, assets = fixture_assets()
        graph = example_graph()
        deck = goal_candidates(task, assets)[0]
        proposal = binding(graph, task, deck)
        args = ("construction-fill-check", "--request", "堆墓", "--task", self.write("task.json", task.to_dict()),
                "--logic", self.write("logic.json", graph.to_dict()), "--proposal", self.write("proposal.json", asdict(proposal)), "--intent-model", self.model_path)
        with patch("ygo_kito.build_pipeline.BuildAssets", return_value=assets), patch("ygo_kito.build_pipeline.verify_goal") as verify:
            code, out, err = self.call(*args)
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["status"], "text_review_unknown")
            reviews = [asdict(text_review(n, (assets.rows[1],))) for n in graph.nodes if n.node_id != "other"]
            code, out, err = self.call(*args, "--reviews", self.write("reviews.json", reviews))
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["status"], "engine_validation_not_run")
            verify.assert_not_called()

    def test_invalid_graph_extra_card_identity_fails_closed(self):
        graph = example_graph().to_dict()
        graph["nodes"][0]["card_id"] = 1
        code, out, err = self.call("construction-plan", "--request", "堆墓", "--logic", self.write("bad.json", graph))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["error"]["code"], "INVALID_INPUT")

    def test_explicit_classifier_fit_cli_saves_learned_scores_and_restores(self):
        from tests.test_intent_model import EXAMPLES
        checkpoint=self.root/"fitted.json"
        code,out,err=self.call("construction-intent-fit","--input",self.write("training.json",EXAMPLES),
            "--output",str(checkpoint),"--epochs","100","--learning-rate","3")
        self.assertEqual(code,0,err)
        report=json.loads(out)
        self.assertLess(report["final_loss"],report["initial_loss"])
        code,out,err=self.call("construction-plan","--request","我要堆墓","--intent-model",str(checkpoint))
        self.assertEqual(code,0,err)
        prediction=json.loads(out)["classification"]
        self.assertEqual(prediction["kind"],"broad")
        self.assertAlmostEqual(sum(prediction["scores"].values()),1.)
        self.assertFalse(prediction["generalization_verified"])

    def test_actual_run_cli_connects_models_catalog_and_coordinator(self):
        from dataclasses import asdict
        from tests.test_construction_binding import catalog, assessment
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from ygo_kito.construction_logic import LogicTag
        from ygo_kito.build_contracts import DeckParts
        task,assets=catalog()
        base=DeckParts(tuple([1]*3+[2]*3+[3]*3+[4]*3+[c for c in range(5,19) for _ in range(2)]))
        tag=LogicTag("effect","送墓")
        binder=CatalogBindingAdapter(assets,assessments=(assessment(assets,1,tag),))
        with patch("ygo_kito.build_pipeline.BuildAssets",return_value=assets):
            code,out,err=self.call("construction-run","--request","堆墓","--task",self.write("task.json",task.to_dict()),
                "--intent-model",self.model_path,"--required-tags",self.write("tags.json",[asdict(tag)]),
                "--binding-data",self.write("binding.json",binder.to_dict()),"--base",self.write("base.json",base.to_dict()),
                "--state-root",str(self.root/"state"),"--verify-existing-goal","--candidate-id","cli-construction")
        self.assertEqual(code,0,err)
        result=json.loads(out)
        self.assertEqual(result["handoff"]["status"],"submitted_existing_coordinator")
        self.assertFalse(result["graph_execution_verified"])
