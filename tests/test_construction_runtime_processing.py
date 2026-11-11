"""Development continuation and online stage progression without model/CB."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.construction_fill import construction_cycle
from ygo_kito.validation import ContractError


class RuntimeModeTests(unittest.TestCase):
    def run_slices(self, rows, **options):
        session = SimpleNamespace(task=None, construction_progress=None)
        calls, checkpoints = [], []
        def step(*args, **kwargs):
            calls.append(kwargs)
            self.assertLessEqual(len(calls), len(rows), 'internal slices must not spin')
            row = deepcopy(rows[len(calls)-1])
            session.construction_progress = row['continuation']
            return row
        with patch('ygo_kito.construction_fill._construction_cycle', side_effect=step):
            result = construction_cycle(session, None, {}, on_progress=lambda r: checkpoints.append(deepcopy(r)), **options)
        return result, calls, checkpoints

    def row(self, reason, *, pending=False, gate=None, passed=False):
        return dict(status='construction_passed' if passed else 'construction_suspended',
            stop_reason=reason, construction_passed=passed, construction_gate=gate,
            continuation=dict(pending_quality={'cursor':1} if pending else None), phases=[])

    def test_development_continues_time_and_iteration_slices(self):
        rows = [self.row('time_slice_exhausted', pending=True), self.row('iteration_slice_exhausted'),
                self.row('construction_passed', passed=True)]
        result, calls, saved = self.run_slices(rows, max_iterations=1, slice_seconds=.001)
        self.assertTrue(result['construction_passed'])
        self.assertEqual(len(saved), 3)
        self.assertTrue(all(c['max_iterations']==1 and c['seconds']==.001 for c in calls))
        self.assertIsNone(result['execution']['deadline_seconds'])

    def test_online_deadline_drains_current_batch_to_real_gate(self):
        gate = dict(status='failed', reasons=['quality_below_reference'])
        rows = [self.row('time_slice_exhausted', pending=True), self.row('iteration_slice_exhausted', gate=gate)]
        result, calls, _ = self.run_slices(rows, run_mode='online', seconds=0., cb_authorized=True)
        self.assertTrue(all(c['max_candidates']==0 and c['cb_authorized'] is False for c in calls))
        self.assertEqual(result['status'], 'construction_delivered')
        self.assertEqual(result['stage_transition']['stage'], 'S5')
        self.assertEqual(result['construction_gate'], gate)
        self.assertFalse(result['construction_passed'])

    def test_real_pause_is_not_automatically_resumed(self):
        result, calls, _ = self.run_slices([self.row('user_pause', pending=True)])
        self.assertEqual(result['stop_reason'], 'user_pause')
        self.assertEqual(len(calls), 1)

    def test_semantic_gap_returns_adapter_work_instead_of_retrying_candidates(self):
        gate = dict(status='pending', reasons=['quality_evaluation_incomplete'])
        result, calls, _ = self.run_slices([self.row('iteration_slice_exhausted', gate=gate)])
        self.assertEqual(result['stop_reason'], 'static_coverage_unresolved')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['construction_gate'], gate)

    def test_configuration_error_is_reported_without_semantic_fallback(self):
        gate = dict(status='pending', reasons=['quality_policy_unconfigured'])
        result, calls, _ = self.run_slices([self.row('iteration_slice_exhausted', gate=gate)])
        self.assertEqual(result['stop_reason'], 'construction_configuration_error')
        self.assertEqual(result['completion_status'], 'configuration_error')
        self.assertEqual(len(calls), 1)

    def test_completed_hard_failure_returns_to_next_optimizer_slice(self):
        gate = dict(status='pending', reasons=['required_function:joint_required:failed'])
        result, calls, _ = self.run_slices([self.row('iteration_slice_exhausted', gate=gate),
            self.row('construction_passed', passed=True, gate=dict(status='passed', reasons=[]))])
        self.assertEqual(len(calls), 2)
        self.assertTrue(result['construction_passed'])

    def test_pending_slice_does_not_increment_completed_failure_counter(self):
        from ygo_kito.construction_progress import record_reference_attempt, FUNCTIONAL_GATE_VERSION
        state = dict(task_sha256='a'*64, candidate_version=1, iteration=1,
            quality_policy={'pass':{'mode':'reference_ratio'}})
        gate = dict(version=FUNCTIONAL_GATE_VERSION, task_sha256=state['task_sha256'],
            candidate_version=1, policy=state['quality_policy'], status='pending',
            reasons=['quality_evaluation_incomplete','quality_pass_line:reference_ratio:unknown'])
        self.assertIsNone(record_reference_attempt(state, gate))
        self.assertNotIn('reference_feedback', state)
        gate.update(reasons=['quality_pass_line:reference_ratio:failed'], evaluation_complete=True)
        self.assertIsNone(record_reference_attempt(state, gate))
        self.assertIsNone(record_reference_attempt(state, gate))
        self.assertEqual(state['reference_feedback']['consecutive_below_reference'], 1)
        state['iteration'] = 2
        self.assertEqual(record_reference_attempt(state, gate)['stage'], 'main_axis')

    def test_explicit_slice_retains_scheduler_contract(self):
        result, calls, _ = self.run_slices([self.row('time_slice_exhausted', pending=True)],
            run_mode='slice', seconds=.01)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['seconds'], .01)
        self.assertEqual(result['stop_reason'], 'time_slice_exhausted')

    def test_development_rejects_online_deadline(self):
        with self.assertRaisesRegex(ContractError, 'development has no task deadline'):
            construction_cycle(SimpleNamespace(task=None), None, {}, seconds=600)

    def test_completed_optimizer_phases_survive_internal_slice_boundaries(self):
        rows = [self.row('time_slice_exhausted', pending=True), self.row('iteration_slice_exhausted'),
                self.row('construction_passed', passed=True)]
        for row, iteration, complete in zip(rows, (1, 1, 2), (False, True, True)):
            row['phases'] = [dict(role='build_optimizer', optimization_iteration=iteration,
                stage_3=dict(selection_complete=complete))]
        result, _, _ = self.run_slices(rows)
        self.assertEqual([p['optimization_iteration'] for p in result['phases']], [1, 2])
        self.assertTrue(all(p['stage_3']['selection_complete'] for p in result['phases']))


class CheckpointTests(unittest.TestCase):
    def test_export_keeps_only_the_working_list_and_cleans_legacy_pending_lists(self):
        import json
        from scripts.run_construction import export_candidate_artifacts
        from ygo_kito.build_contracts import digest
        task = {'sizes': {'main': 40, 'extra': 15, 'side': 15}}
        skeleton = {'deck': {'main': [1], 'extra': [], 'side': []}}
        deck = {'main': list(range(1, 41)), 'extra': list(range(41, 56)), 'side': list(range(56, 71))}
        with TemporaryDirectory() as directory:
            output = Path(directory)
            (output/'pending-candidate-01.json').write_text(json.dumps({'deck': deck}), encoding='utf-8')
            (output/'pending-candidate-01.ydk').write_text('old candidate', encoding='utf-8')
            (output/'reference.ydk').write_text('user reference', encoding='utf-8')
            complete, pending = export_candidate_artifacts(output, task, skeleton,
                {'pending_quality': {'candidates': [{'deck': deck}], 'evaluations': {}}})
            self.assertFalse(complete)
            self.assertFalse((output/'deck.ydk').exists())
            self.assertTrue((output/'skeleton.json').is_file())
            self.assertEqual(pending, [dict(candidate_index=0, status='static_evaluation_pending',
                                            deck_sha256=digest(deck))])
            self.assertFalse(list(output.glob('pending-candidate-*')))
            record = json.loads((output/'candidate-exports.json').read_text(encoding='utf-8'))
            self.assertEqual(record['pending_candidates'], pending)
            complete, pending = export_candidate_artifacts(output, task, {'deck': deck}, {})
            self.assertTrue(complete)
            self.assertTrue((output/'deck.ydk').is_file())
            self.assertFalse((output/'skeleton.json').exists())
            self.assertTrue((output/'reference.ydk').is_file())
            self.assertEqual(pending, [])

    def test_compaction_keeps_pending_work_only_in_authoritative_progress(self):
        from ygo_kito.build_contracts import digest
        from ygo_kito.construction_progress import compact_completed_progress, construction_report
        winner = dict(deck=dict(main=[1], extra=[], side=[]), strategy='incumbent')
        loser = dict(deck=dict(main=[2], extra=[], side=[]))
        delta = dict(main=dict(added=[1], removed=[2]))
        trace = dict(candidates=[dict(candidate_index=0, recognition_inventory=winner['deck'], selected=True),
                                 dict(candidate_index=1, recognition_inventory=loser['deck'], selected=False)],
                     generation=dict(legal_edit_candidates=2, discarded_edits=[delta]))
        phase = dict(role='build_optimizer', input_deck=loser['deck'], proposal_deck=winner['deck'],
            proposal_changes=delta, stage_3=dict(candidate_trace=trace, attempts=[loser], portfolio=[winner, loser]))
        pending = dict(candidates=[loser])
        state = dict(candidate=dict(winner, changes=delta), candidate_version=2,
            retained_candidates=[winner, loser], last_optimizer_phase=phase, pending_quality=pending)
        compact_completed_progress(state)
        self.assertEqual(state['candidate'], winner)
        self.assertEqual(state['retained_candidates'], [])
        self.assertIs(state['pending_quality'], pending)
        phase = state['last_optimizer_phase']
        self.assertEqual(phase['input_deck_sha256'], digest(loser['deck']))
        self.assertNotIn('proposal_changes', phase)
        self.assertEqual(phase['stage_3']['candidate_trace']['candidates'][1],
                         dict(candidate_index=1, deck_sha256=digest(loser['deck']), selected=False))
        self.assertNotIn('attempts', phase['stage_3'])
        self.assertNotIn('portfolio', phase['stage_3'])
        result = dict(best=winner, verified_best=winner, construction_candidate=winner,
                      retained_candidates=[winner], continuation=state, phases=[phase])
        self.assertEqual(construction_report(result), dict(best=winner, phases=[phase]))

    def test_course_removes_only_its_discarded_route_and_cb_records(self):
        import json
        from scripts.local_course_collaboration import retire_candidate_proofs
        winner, loser = dict(main=[1], extra=[], side=[]), dict(main=[2], extra=[], side=[])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            keep = {'route-002.json': winner, 'basic-cb-inference-004.json': winner,
                    'older-course.json': loser, 'route-training.json': loser}
            remove = {'route-001.json': loser, 'basic-cb-inference-003.json': loser}
            for name, deck in {**keep, **remove}.items():
                (root/name).write_text(json.dumps({'deck': deck}), encoding='utf-8')
            retire_candidate_proofs(root, winner)
            self.assertEqual({file.name for file in root.iterdir()}, set(keep))

    def test_commit_survives_temporary_and_lagging_export(self):
        from ygo_kito.construction_checkpoint import ConstructionCheckpoint, write_json
        from ygo_kito.validation import read_json

        with TemporaryDirectory() as directory:
            root = Path(directory)
            kernel, export = root/'kernel.json', root/'session.json'
            checkpoint = ConstructionCheckpoint(kernel)
            legacy = dict(schema_version=1, selections={}, sessions={})
            write_json(kernel, legacy)
            self.assertEqual(checkpoint.read(kernel)['state'], legacy)
            self.assertEqual(checkpoint.read(kernel)['revision'], 0)
            checkpoint.commit({'iteration': 1}, stop_reason='time_slice_exhausted')
            checkpoint.export_session(export, {'iteration': 1})
            with patch.object(Path, 'replace', side_effect=PermissionError('controlled replace failure')):
                with self.assertRaises(PermissionError):
                    checkpoint.commit({'iteration': 2}, stop_reason='time_slice_exhausted')
            self.assertEqual(checkpoint.revision, 1)
            self.assertEqual(checkpoint.read(kernel)['state']['iteration'], 1)
            temporary = kernel.with_suffix('.json.tmp')
            self.assertEqual(read_json(temporary)['state']['iteration'], 2)
            with self.assertRaises(ContractError):
                checkpoint.read(temporary)
            checkpoint.commit({'iteration': 2}, stop_reason='user_pause')
            with patch.object(Path, 'replace', side_effect=PermissionError('controlled export failure')):
                with self.assertRaises(PermissionError):
                    checkpoint.export_session(export, {'iteration': 2})
            self.assertEqual(checkpoint.read(kernel)['revision'], 2)
            self.assertEqual(checkpoint.read(kernel)['stop_reason'], 'user_pause')
            self.assertEqual(read_json(export)['revision'], 1)
            with self.assertRaises(ContractError):
                checkpoint.read(export)

    def test_compressed_checkpoint_is_atomic_and_reads_legacy_json(self):
        import gzip
        from ygo_kito.construction_checkpoint import ConstructionCheckpoint, KERNEL_FILENAME, LEGACY_KERNEL_FILENAME
        state = {'pending': {'candidates': [{'deck': ['同名卡'] * 40}] * 8}}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plain = ConstructionCheckpoint(root/LEGACY_KERNEL_FILENAME)
            zipped = ConstructionCheckpoint(root/KERNEL_FILENAME)
            plain.commit(state, stop_reason='user_pause')
            zipped.commit(state, stop_reason='user_pause')
            self.assertEqual(plain.read(plain.path), zipped.read(zipped.path))
            self.assertLess(zipped.path.stat().st_size, plain.path.stat().st_size)
            with gzip.open(zipped.path, 'rt', encoding='utf-8') as encoded:
                self.assertIn('同名卡', encoded.read())
            with patch.object(Path, 'replace', side_effect=PermissionError('controlled replace failure')):
                with self.assertRaises(PermissionError):
                    zipped.commit({'lost': True}, stop_reason='user_pause')
            self.assertEqual(zipped.revision, 1)
            self.assertEqual(zipped.read(zipped.path)['state'], state)
            with self.assertRaises(ContractError):
                zipped.read(zipped.path.with_suffix('.gz.tmp'))

    def test_pause_during_cli_checkpoint_is_committed_before_a_new_slice(self):
        from scripts.run_construction import advance_construction
        from ygo_kito.construction_checkpoint import ConstructionCheckpoint

        with TemporaryDirectory() as directory:
            path = Path(directory)/'kernel.json'
            checkpoint = ConstructionCheckpoint(path)
            session = SimpleNamespace(task=None, construction_progress=None)
            paused, calls = False, []
            replace = Path.replace

            def replace_and_pause(temporary, destination):
                nonlocal paused
                result = replace(temporary, destination)
                if destination == path:
                    paused = True
                return result

            def step(*_args, **_options):
                calls.append(1)
                state = session.construction_progress or dict(iteration=1, pending_quality={'evaluations': {}})
                session.construction_progress = state
                return dict(status='construction_suspended', construction_passed=False, phases=[],
                            stop_reason='time_slice_exhausted', continuation=state)

            class Kernel:
                def state_dict(self, *, for_write):
                    return session.construction_progress

                def run_selected(self, _selection, *, base, basic_cb_enabled, **options):
                    return construction_cycle(session, None, {}, **options)

            with patch('ygo_kito.construction_fill._construction_cycle', side_effect=step), \
                 patch.object(Path, 'replace', replace_and_pause):
                result = advance_construction(Kernel(), {}, checkpoint, pause_requested=lambda: paused,
                                              status=lambda *_a, **_kw: None, run_mode='online', seconds=0.)
            self.assertEqual(calls, [1])
            self.assertEqual(result['completion_status'], 'user_stopped')
            saved = checkpoint.read(path)
            self.assertEqual(saved['revision'], 2)
            self.assertEqual(saved['stop_reason'], 'user_pause')
            self.assertEqual(saved['state'], dict(iteration=1, stop_reason='user_pause', pending_quality={'evaluations': {}}))
            session.construction_progress = saved['state']
            with patch('ygo_kito.construction_fill._construction_cycle', side_effect=step):
                resumed = advance_construction(Kernel(), {}, checkpoint, pause_requested=lambda: False,
                                               status=lambda *_a, **_kw: None, run_mode='slice')
            self.assertEqual(calls, [1, 1])
            self.assertEqual(resumed['continuation']['iteration'], 1)
            self.assertEqual(checkpoint.read(path)['revision'], 3)


class ProcessingInventoryTests(unittest.TestCase):
    def check(self, movements, *, optional=None, selected=None):
        from tests.test_construction_functional_flow import fixture
        from ygo_kito.construction_inventory import InventoryDependencies
        task, assets, _, binder, decks, _ = fixture()
        assets.rows[1].update(type=17, desc='通常怪兽。')
        operations = [dict(kind='return' if dest=='hand' else 'send_grave', from_zones=[origin], to_zone=dest,
            source='printed movement '+str(i), block_id='movement:'+str(i), order=i,
            owner='self', quantity=1, random=False, reason='effect',
            selector_query={'predicate':{'field':'card_ids','value':[1]}})
            for i, (origin, dest) in enumerate(movements)]
        if optional is not None:
            operations[optional]['optional'] = True
        record = dict(source_text='ordered complete processing', costs=[], operations=operations,
            restrictions=[], card_restrictions=[])
        return InventoryDependencies(binder.semantic_catalog).processing_check(decks[1], record,
            operations[selected] if selected is not None else None)

    def test_returned_entity_is_available_only_in_printed_destination(self):
        valid = self.check([('deck','grave'), ('grave','hand'), ('hand','grave')])
        self.assertEqual(valid['status'], 'inventory_present', valid)
        impossible = self.check([('deck','grave'), ('grave','hand'), ('deck','grave')])
        self.assertEqual(impossible['status'], 'missing', impossible)

    def test_unselected_optional_processing_does_not_reserve_stock(self):
        movements = [('hand','field'), ('hand','grave')]
        self.assertIsNone(self.check(movements, optional=1, selected=0))
        self.assertEqual(self.check(movements, optional=1, selected=1)['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
