"""Actual CPU checkpoint envelopes only; no games, optimizer steps or native."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import tests.test_scenario_course as scenario_fixtures
from ygo_kito.scenario_course import checkpoint_policy
from ygo_kito.validation import ContractError


class ScenarioStorageTests(unittest.TestCase):
    def setUp(self):
        self.fixture=scenario_fixtures.ScenarioCourseTests('test_already_checkpointed_bo1_draw_closes_once_without_sampling_again')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def course(self,policy=None):
        if policy is not None:self.fixture.config['checkpoint_policy']=policy
        return self.fixture.new_course()

    def test_default_preserves_all_checkpoint_and_unrelated_files(self):
        course=self.course()
        unrelated=course.root/'checkpoint-900.weights';unrelated.write_bytes(b'user file not adopted')
        receipt=course.root/'user-receipt.json';receipt.write_text('{}')
        before=hashlib.sha256(course.data_index.path.read_bytes()).hexdigest()
        for _ in range(4):course.save()
        self.assertTrue(all((course.root/('checkpoint-'+str(i)+'.weights')).is_file() for i in range(1,5)))
        self.assertEqual(unrelated.read_bytes(),b'user file not adopted')
        self.assertTrue(receipt.exists())
        self.assertEqual(hashlib.sha256(course.data_index.path.read_bytes()).hexdigest(),before)
        self.assertIsNone(course.storage_status()['checkpoint_policy']['keep_last'])
        self.assertFalse(course.storage_status()['whole_environment_under_30GB_proven'])

    def test_retention_keeps_latest_initial_milestones_and_exact_restore(self):
        course=self.course({'keep_last':2,'milestone_every':3})
        for _ in range(7):course.save()
        self.assertEqual(sorted(p.name for p in course.root.glob('checkpoint-*.weights')),
            ['checkpoint-1.weights','checkpoint-3.weights','checkpoint-6.weights','checkpoint-7.weights'])
        manifest=json.loads((course.root/'checkpoint-manifest.json').read_text())
        self.assertEqual(len(manifest['entries']),7)  # Append-only ownership evidence.
        before=course.models.fingerprint()
        resumed=self.fixture.new_course();resumed.restore_latest()
        self.assertEqual(resumed.models.fingerprint(),before)
        self.assertEqual(resumed.revision,7)
        resumed.save()
        self.assertTrue((resumed.root/'checkpoint-8.weights').exists())
        self.assertTrue((resumed.root/'checkpoint-1.weights').exists())
        self.assertTrue((resumed.root/'checkpoint-3.weights').exists())
        self.assertEqual(resumed.storage_status()['manifest_entries'],8)

    def test_manifest_tampering_rejected_before_pruning_or_model_restore(self):
        course=self.course({'keep_last':1})
        for _ in range(3):course.save()
        path=course.root/'checkpoint-manifest.json'
        value=json.loads(path.read_text());value['entries'][0]['sha256']='0'*64
        path.write_text(json.dumps(value))
        existing={p.name:p.read_bytes() for p in course.root.glob('*.weights')}
        with self.assertRaises(ContractError):course.save()
        with patch.object(course.models,'restore_state',side_effect=AssertionError('models must not restore')):
            with self.assertRaises(ContractError):self.fixture.new_course().restore_latest()
        self.assertEqual({p.name:p.read_bytes() for p in course.root.glob('*.weights')},existing)

    def test_owned_bytes_tamper_stops_entire_pruning_before_any_unlink(self):
        course=self.course({'keep_last':2})
        for _ in range(3):course.save()
        candidate=course.root/'checkpoint-2.weights'  # Would become prunable on save 4.
        candidate.write_bytes(candidate.read_bytes()+b'changed')
        with self.assertRaises(ContractError):course.save()
        self.assertTrue((course.root/'checkpoint-1.weights').exists())
        self.assertTrue((course.root/'checkpoint-3.weights').exists())
        self.assertTrue(candidate.read_bytes().endswith(b'changed'))
        self.assertEqual(course.revision,3)

    def test_lookalike_checkpoint_index_markers_and_user_receipts_are_never_pruned(self):
        course=self.course({'keep_last':1})
        user=course.root/'checkpoint-99.weights';user.write_bytes(b'not in manifest')
        markers=[]
        for name in ('pause.request','in-flight.json','feedback-in-flight.json','private-receipt.json'):
            path=course.root/name;path.write_text('private evidence');markers.append(path)
        index=course.data_index.path.read_bytes()
        for _ in range(4):course.save()
        self.assertEqual(user.read_bytes(),b'not in manifest')
        self.assertTrue(all(p.read_text()=='private evidence' for p in markers))
        self.assertEqual(course.data_index.path.read_bytes(),index)
        self.assertTrue((course.root/'checkpoint-1.weights').exists())
        self.assertTrue((course.root/'checkpoint-4.weights').exists())
        self.assertFalse((course.root/'checkpoint-2.weights').exists())

    def test_space_guards_block_before_game_and_before_checkpoint_publication(self):
        course=self.course({'min_free_bytes':1000})
        with patch('ygo_kito.scenario_course.shutil.disk_usage',return_value=SimpleNamespace(free=999)):
            with patch('ygo_kito.scenario_course.CourseGameAdapter',side_effect=AssertionError('game must not start')):
                with self.assertRaises(ContractError):course._game()
            with self.assertRaises(ContractError):course.save()
        self.assertEqual(course.revision,0)
        self.assertFalse((course.root/'latest.json').exists())
        # Current usage fits, but an actual serialized checkpoint plus transient
        # metadata would not; refusal occurs without publishing any new file.
        free=course._storage_bytes()+1
        self.fixture.config['checkpoint_policy']={'max_state_bytes':free}
        course=self.fixture.new_course()
        with self.assertRaises(ContractError):course.save()
        self.assertEqual(course.revision,0)
        self.assertEqual(list(course.root.glob('*.weights')),[])

    def test_max_state_counts_external_index_and_refuses_unsafe_policy_values(self):
        course=self.course({'max_state_bytes':1})
        self.assertGreater(course.data_index.path.stat().st_size,1)
        with self.assertRaises(ContractError):course._storage_guard()
        for value in ({'keep_last':0},{'keep_last':True},{'milestone_every':-1},{'min_free_bytes':-1},
                      {'max_state_bytes':0},{'unknown_field':1}):
            with self.subTest(value=value),self.assertRaises(ContractError):checkpoint_policy(value)

    def test_manifest_cannot_add_a_user_file_to_pruning_set(self):
        course=self.course({'keep_last':1})
        course.save();course.save()
        owned=course.root/'checkpoint-manifest.json';value=json.loads(owned.read_text())
        unrelated=course.root/'checkpoint-123.weights';unrelated.write_bytes(b'never owned')
        forged=deepcopy(value['entries'][-1]);forged.update(path=unrelated.name,revision=123,
            bytes=unrelated.stat().st_size,sha256=hashlib.sha256(unrelated.read_bytes()).hexdigest(),initial=False)
        value['entries'].append(forged);owned.write_text(json.dumps(value))
        with self.assertRaises(ContractError):course.save()
        with self.assertRaises(ContractError):self.fixture.new_course().restore_latest()
        self.assertEqual(unrelated.read_bytes(),b'never owned')


if __name__=='__main__':unittest.main()
