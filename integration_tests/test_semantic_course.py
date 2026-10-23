"""Actual two-cycle schema4 updates, stage crashes and index checkpointing."""
import copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
import torch

from ygo_kito.group_runner import GroupState,sampler
from ygo_kito.group_runner_acceptance import run_group_acceptance
from ygo_kito.local_training import LocalCpuBackend,verified_trainer
from ygo_kito.validation import ContractError,read_json
from ygo_kito.lora_group import construction_loss,ppo_inputs
from ygo_kito.duel_model import parameter_digest
from ygo_kito.contracts import DecisionRequest

ROOT=Path(__file__).resolve().parents[1]


class IndexedSemanticCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        retained=os.environ.get('YGO_KITO_COURSE_ARTIFACT_ROOT')
        cls.temp=None
        if retained:
            cls.folder=Path(retained).resolve()
            if not cls.folder.is_relative_to(ROOT/'.cache') or cls.folder.exists():
                raise ContractError('explicit test evidence must be a new cloud cache directory')
            cls.folder.mkdir(parents=True)
        else:
            cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        cls.proof=run_group_acceptance(ROOT/'.cache',cls.folder,'indexed-course',read_json(ROOT/'configs/group-combined-v1.json'))
        cls.host=cls.folder/'experiments/indexed-course/host';cls.run_dir=cls.host/'runs/group-interrupted'
        cls.backend=LocalCpuBackend(cls.host,ROOT/'.cache');cls.row=cls.backend.details('group-interrupted')
        cls.state=verified_trainer(cls.host,cls.row)

    @classmethod
    def tearDownClass(cls):
        if cls.temp is not None:cls.temp.cleanup()

    def test_actual_four_role_updates_and_inner_alternation_preserve_semantic_goal(self):
        p,s=self.proof,self.state
        self.assertTrue(p['ok']);self.assertEqual(s.cursor(),{'cycle':2,'phase':'done','committed_stages':13})
        self.assertEqual(p['final_snapshot']['role_adapter_updates'],{r:2 for r in s.models()})
        self.assertEqual(s.data['source'],'catalog_constraint_and_explicit_preference_v1')
        self.assertEqual(len(s.construction_state['consumed']),6)
        for event in s.events:
            if event['event_id'].endswith('build_goal'):
                self.assertEqual(event['payload']['construction']['validation']['status'],'constraints_and_route_verified')
            if event['event_id'].endswith('build_optimizer'):
                stages=event['payload']['construction']['stages']
                self.assertEqual([x['role'] for x in stages],['build_goal','build_optimizer']*2)
                for stage in stages:
                    self.assertTrue(stage['validation']['effect_execution_verified'])
                    self.assertEqual(stage['task_sha256'],s.task.sha256)
        for update in p['updates_after_final']:
            self.assertGreater(update.get('parameter_delta_l2',update.get('adapter_delta_l2')),0)

    def test_real_pause_crash_and_stage_budget_restore_without_duplicate_committed_data(self):
        self.assertTrue(self.proof['continuous_recovery_equal']);self.assertTrue(self.proof['stage_budget_resume_equal'])
        self.assertEqual(self.proof['discarded_optimizer_calls'],0)
        self.assertEqual(len(self.state.data_marks),5)
        self.assertEqual(self.state.data_index.summary()['by_purpose'],{'train':4,'validation':3,'final_eval':0})
        self.assertEqual(self.state.data_index.summary()['artifacts'],7)
        self.assertEqual(len({m['indexed_artifact_id'] for m in self.state.data_marks}),5)
        self.assertTrue(all(m.get('private_audit') for m in self.state.data_marks))
        self.assertTrue(all(e['payload']['training_state_unchanged'] for e in self.state.events if e['event_id'].endswith('evaluate')))
        self.assertFalse(self.proof['formal_training_ready'])

    def test_checkpoint_embeds_index_bytes_and_rejects_corruption_before_training(self):
        path=self.run_dir/'checkpoints/local-step-13.weights';saved=torch.load(path,weights_only=True)
        snapshot=saved['data_index_snapshot'];self.assertEqual(hashlib.sha256(snapshot['bytes']).hexdigest(),snapshot['sha256'])
        self.assertGreater(len(snapshot['bytes']),4096)
        original=self.state.versions();bad=copy.deepcopy(saved);bad['data_index_snapshot']['sha256']='0'*64
        broken=self.folder/'bad-index.weights';torch.save(bad,broken)
        with self.assertRaisesRegex(ContractError,'index checksum'):
            GroupState.restore(broken,self.host,self.row,self.state.assets)
        self.assertEqual(self.state.versions(),original)

    def test_heldout_construction_and_relabelled_real_ppo_are_rejected_before_rng_or_weights_change(self):
        s=self.state;held=s.data_index.artifact('build-labels-validation')['payload'];session=s.sessions['build_goal']
        before=parameter_digest(session.model);rng=session.rng.get_state().clone()
        with self.assertRaises(ContractError):construction_loss('build_goal',session,s.builder,s.task,held)
        self.assertTrue(torch.equal(session.rng.get_state(),rng));self.assertEqual(parameter_digest(session.model),before)
        mark=next(m for m in reversed(s.data_marks) if m['partition']=='validation')
        raw=s.data_index.artifact(mark['indexed_artifact_id'])['payload']
        episode=copy.deepcopy(raw)
        for step in episode['steps']:step['request']=DecisionRequest.from_dict(step['request'])
        episode['purpose']=episode['summary']['purpose']='train'
        actor=s.sessions['duel'];rng=actor.rng.get_state().clone();before=parameter_digest(actor.model)
        with self.assertRaisesRegex(ContractError,'fresh indexed'):
            ppo_inputs(episode,sampler(s),actor)
        self.assertTrue(torch.equal(actor.rng.get_state(),rng));self.assertEqual(parameter_digest(actor.model),before)
