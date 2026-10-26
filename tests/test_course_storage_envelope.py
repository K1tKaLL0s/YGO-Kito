"""Actual CPU save/restore through bounded sinks, no games or native calls."""
import hashlib
import json
import unittest
from unittest.mock import patch

import tests.test_scenario_course as scenario_fixtures
import tests.test_selfplay_series as series_fixtures
from tests.test_cpu_takeover_routes import route_fixture
from ygo_kito.data_isolation import DataIndex
from ygo_kito.scenario_course import ScenarioCourse
from ygo_kito.scenario_course_host import ScenarioCourseHost
from ygo_kito.selfplay_series import SelfPlaySeries
from ygo_kito.storage_envelope import StorageEnvelope
from ygo_kito.validation import ContractError


class CourseEnvelopeTests(unittest.TestCase):
    def scenario_fixture(self):
        f = scenario_fixtures.ScenarioCourseTests('test_already_checkpointed_bo1_draw_closes_once_without_sampling_again')
        f.setUp(); self.addCleanup(f.doCleanups); return f

    def course(self, f, envelope, index=None):
        return ScenarioCourse(f.models, assets=f.host.assets, data_index=index or f.host.index,
            config=f.config, state_root=f.host.root/'scenario-state', bots=f.bots, storage_envelope=envelope)

    def test_real_course_checkpoint_uses_reserved_sink_and_restores_exact_models(self):
        f = self.scenario_fixture()
        env = StorageEnvelope(f.host.root, state_roots=['scenario-state'], outside_bytes=0, min_free_bytes=0)
        c = self.course(f, env); before = c.models.fingerprint(); pointer = c.save()
        checkpoint = c.root/pointer['path']
        self.assertEqual(hashlib.sha256(checkpoint.read_bytes()).hexdigest(), pointer['sha256'])
        receipts = list(env.control.glob('*.complete.json'))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())['artifact_sha256'], pointer['sha256'])
        resumed = self.course(f, env); resumed.restore_latest()
        self.assertEqual(resumed.models.fingerprint(), before)
        env.outside_bytes = 1
        with self.assertRaises(ContractError): resumed.save()

    def test_declared_index_limits_are_bound_and_survive_reopen(self):
        f = self.scenario_fixture()
        f.config['data_index_storage'] = {'max_database_bytes': 1024*1024, 'max_artifact_bytes': 65536}
        index = DataIndex(f.host.root/'bounded-index', storage_limits=f.config['data_index_storage'])
        c = self.course(f, None, index); c.save()
        self.assertEqual(c.binding['data_index_storage_sha256'], index.storage_policy_sha256)
        reopened = DataIndex(index.root)
        self.course(f, None, reopened).restore_latest()
        f.config['data_index_storage']['max_artifact_bytes'] += 1
        with self.assertRaises(ContractError): self.course(f, None, reopened)

    def test_existing_pilot_path_inherits_actual_index_limits_before_sampling(self):
        f = self.scenario_fixture()
        limits = {'max_database_bytes': 1024*1024, 'max_artifact_bytes': 65536}
        index = DataIndex(f.host.root/'bounded-index', storage_limits=limits)
        c = self.course(f, None, index)
        with patch('ygo_kito.scenario_course.DataIndex', side_effect=ContractError('stop before sampling')) as factory:
            with self.assertRaisesRegex(ContractError, 'stop before sampling'):
                c.timing_pilot([(900, 901)])
        self.assertEqual(factory.call_args.kwargs['storage_limits'], limits)

    def test_bound_envelope_cannot_be_removed_replaced_or_point_outside_state(self):
        f = self.scenario_fixture()
        env = StorageEnvelope(f.host.root, state_roots=['scenario-state'], outside_bytes=0, min_free_bytes=0)
        c = self.course(f, env)
        for replacement in (None, StorageEnvelope(f.host.root, state_roots=['scenario-state'], outside_bytes=0)):
            c.storage_envelope = replacement
            with self.assertRaisesRegex(ContractError, 'instance changed'): c._storage_guard()
        wrong = StorageEnvelope(f.host.root, state_roots=['elsewhere'], outside_bytes=0)
        with self.assertRaisesRegex(ContractError, 'outside the declared'): self.course(f, wrong)

    def test_unknown_external_usage_blocks_host_preflight_without_new_state(self):
        with route_fixture() as (root, spec, config, save, timing):
            spec['storage_envelope'] = save('space.json', {'state_roots': ['private-state']})
            before = set(root.rglob('*'))
            result = ScenarioCourseHost(root, spec).preflight()
            self.assertEqual(result['status'], 'blocked')
            self.assertIn('storage budget is unknown', result['blockers'][0]['message'])
            self.assertEqual(set(root.rglob('*')), before)

    def test_host_rejects_uncovered_state_before_model_initialization_or_writes(self):
        with route_fixture() as (root, spec, config, save, timing):
            spec['storage_envelope'] = save('space.json', {'state_roots': ['elsewhere'], 'outside_bytes': 0})
            before = set(root.rglob('*'))
            with patch('ygo_kito.course_models.CourseModels.initialize', side_effect=AssertionError('not before storage coverage')):
                result = ScenarioCourseHost(root, spec).preflight()
            self.assertEqual(result['status'], 'blocked')
            self.assertIn('outside the declared', result['blockers'][0]['message'])
            self.assertEqual(set(root.rglob('*')), before)

    def test_real_two_group_checkpoint_and_history_blobs_use_reserved_sink(self):
        f = series_fixtures.SelfPlaySeriesTests('test_initial_pool_actual_independent_groups_and_disabled_training')
        # unittest's named method is not run here; only the fixture setup is used.
        f.setUp(); self.addCleanup(f.doCleanups)
        env = StorageEnvelope(f.f.root, state_roots=['series'], outside_bytes=0, min_free_bytes=0)
        series = SelfPlaySeries(players=tuple(f.players), assets=f.assets, data_index=f.f.index,
            state_root=f.f.root/'series', config=f.config, storage_envelope=env)
        before = {p.player_id: p.models.fingerprint() for p in f.players}
        series.save()
        self.assertGreaterEqual(len(list(env.control.glob('*.complete.json'))), 3)  # Two real snapshots + CP.
        series.restore_latest()
        self.assertEqual(before, {p.player_id: p.models.fingerprint() for p in f.players})
        self.assertEqual(series.status()['formal_training_matches'], 0)
        series.storage_envelope = None
        with self.assertRaisesRegex(ContractError, 'instance changed'): series.save()


if __name__ == '__main__': unittest.main()
