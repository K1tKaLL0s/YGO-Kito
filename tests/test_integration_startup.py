"""Full source checkout/process startup; no native, external provider or worker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ygo_kito.agent_driver import Client, RemoteError, StreamTransport
from tests.test_construction_logic import fixture_classifier
from tests.test_build_contracts import TASK

ROOT=Path(__file__).resolve().parents[1]


class ProjectStartupTests(unittest.TestCase):
    def setUp(self):
        cache=ROOT/".cache";cache.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix="integration-startup-",dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.env=dict(os.environ,PYTHONPATH=str(ROOT/"src"),OMP_NUM_THREADS="2",MKL_NUM_THREADS="2")

    def command(self,*args):
        return subprocess.run([sys.executable,"-m","ygo_kito",*args],cwd=self.folder,env=self.env,
            text=True,capture_output=True,timeout=20)

    def test_full_checkout_status_and_help_start_without_prepared_native(self):
        result=self.command("status")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(json.loads(result.stdout)["engine"]["ready"])
        help_result=self.command("--help")
        self.assertEqual(help_result.returncode,0,help_result.stderr)
        self.assertIn("construction-run",help_result.stdout)

    def test_real_stdio_manager_process_dp_client_and_learned_plan(self):
        model=self.folder/"intent.json";fixture_classifier().save(model)
        bindings=self.folder/"bindings.json";bindings.write_text("{}",encoding="utf-8")
        config=self.folder/"construction.json"
        config.write_text(json.dumps({"intent_model":str(model.relative_to(ROOT)),"binding_data":str(bindings.relative_to(ROOT))}),encoding="utf-8")
        process=subprocess.Popen([sys.executable,"-m","ygo_kito","agent-serve","--role","manager",
            "--construction-config",str(config),"--state-root",str(self.folder/"state"),"--root",str(self.folder/"missing-native")],
            cwd=self.folder,env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
        try:
            client=Client(StreamTransport(process.stdout,process.stdin))
            caps=client.capabilities()
            self.assertFalse(caps["provider_connected"])
            self.assertTrue(caps["construction_backend_configured"])
            self.assertTrue(client.has("construction.plan"))
            result=client.call("construction.plan",{"request":"堆墓"})
            self.assertEqual(result["classification"]["kind"],"broad")
            self.assertEqual(result["route"]["stages"],[1,3])
            with self.assertRaises(RemoteError) as denied:
                client.call("training.control",{})
            self.assertEqual(denied.exception.code,"PERMISSION_DENIED")
            with self.assertRaises(RemoteError) as missing:
                client.call("construction.run",{"request":"堆墓","task":TASK,
                    "required_tags":[{"dimension":"effect","value":"送墓"}]})
            self.assertEqual(missing.exception.code,"CONSTRUCTION_RESOURCES_UNAVAILABLE")
            process.stdin.close()
            self.assertEqual(process.wait(timeout=10),0,process.stderr.read())
        finally:
            if process.poll() is None:
                process.stdin.close()
                process.wait(timeout=10)
            process.stdout.close();process.stderr.close()

    def test_manager_configuration_does_not_expand_monitor_authority(self):
        result=self.command("agent-call",str(self.folder/"not-read.json"),"--role","monitor",
            "--construction-config",str(self.folder/"not-read-config.json"))
        self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stderr)["error"]["code"],"INVALID_INPUT")
        self.assertFalse((self.folder/"state").exists())
