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
from tests.test_construction_logic import binding, example_graph, fixture_assets, text_review
from ygo_kito.build_pipeline import goal_candidates


class ConstructionCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

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
        self.assertEqual(json.loads(result.stdout)["route"]["stages"], [1, 2, 3])

    def test_plan_graph_roundtrip_and_dictionary_extension_keep_defaults(self):
        graph = example_graph()
        vocabulary = self.write("lexicon.json", {"terms": [{"canonical": "星河织梦", "kind": "theme", "aliases": ["星织"]}]})
        for request, expected in (("星织堆墓", [1, 2, 3]), ("不要珠泪，只要堆墓", [1, 3]), ("未知裸名", [1])):
            code, out, err = self.call("construction-plan", "--request", request,
                "--logic", self.write("logic.json", graph.to_dict()), "--lexicon", vocabulary)
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
                "--logic", self.write("logic.json", graph.to_dict()), "--proposal", self.write("proposal.json", asdict(proposal)))
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
