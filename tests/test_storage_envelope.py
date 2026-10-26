"""Small KiB-only real allocation/writes; no models, SQL, engine or training."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.storage_envelope import main
from ygo_kito.storage_envelope import StorageEnvelope,StorageEnvelopeExceeded,workspace_usage,LIMIT_BYTES
from ygo_kito.validation import ContractError


class StorageEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'state').mkdir();(self.root/'temporary').mkdir()

    def envelope(self,**options):
        args={'state_roots':['state'],'temporary_roots':['temporary'],'outside_bytes':0,
            'min_free_bytes':0,'safety_margin_bytes':0,'limit_bytes':1024*1024}
        args.update(options);return StorageEnvelope(self.root,**args)

    def test_default_audit_never_creates_files_and_external_environment_stays_unknown(self):
        before=set(self.root.rglob('*'))
        env=StorageEnvelope(self.root,state_roots=['state'])
        report=env.audit()
        self.assertIsNone(report['outside_bytes']);self.assertIsNone(report['conservative_accounted_total_bytes'])
        self.assertFalse(report['current_admission_passed']);self.assertFalse(report['training_authorized'])
        self.assertFalse(report['minimum_training_volume_completion_verified'])
        self.assertEqual(set(self.root.rglob('*')),before)
        with self.assertRaises(StorageEnvelopeExceeded):env.reserve_file('unknown','state/unknown.bin',4096)
        self.assertEqual(set(self.root.rglob('*')),before)

    def test_strict_less_than_total_rejects_equality_and_30GB_threshold_cannot_increase(self):
        used=workspace_usage(self.root)['accounted_bytes']
        env=self.envelope(limit_bytes=used+1024)
        self.assertTrue(env.guard(1023)['current_admission_passed'])
        with self.assertRaises(StorageEnvelopeExceeded):env.guard(1024)
        with self.assertRaises(ContractError):self.envelope(limit_bytes=LIMIT_BYTES+1)
        with self.assertRaises(ContractError):self.envelope(outside_bytes=True)

    def test_real_preallocation_and_bounded_commit_never_overwrite_old_user_files(self):
        env=self.envelope();existing=self.root/'state/user.bin';existing.write_bytes(b'user-owned')
        with self.assertRaises(ContractError):env.reserve_file('old','state/user.bin',4096)
        self.assertEqual(existing.read_bytes(),b'user-owned')
        with env.reserve_file('one','state/new.bin',4096) as sink:
            self.assertEqual(sink.part.stat().st_size,4096)
            self.assertGreaterEqual(sink.part.stat().st_blocks*512,4096)
            sink.write(b'abc');sink.seek(1);sink.write(b'Z');sink.seek(0,2);sink.write(b'd')
            receipt=sink.commit()
            self.assertEqual(sink.commit(),receipt)
        self.assertEqual((self.root/'state/new.bin').read_bytes(),b'aZcd')
        self.assertEqual(receipt['artifact_sha256'],hashlib.sha256(b'aZcd').hexdigest())
        self.assertFalse((env.control/'one.part').exists())
        self.assertTrue((env.control/'one.complete.json').exists())
        self.assertEqual(existing.read_bytes(),b'user-owned')

    def test_overflow_or_exception_retains_part_and_receipt_without_publishing(self):
        env=self.envelope()
        with self.assertRaises(StorageEnvelopeExceeded):
            with env.reserve_file('too-big','temporary/data.bin',4096) as sink:
                sink.write(b'x'*4096);sink.write(b'y')
        self.assertFalse((self.root/'temporary/data.bin').exists())
        self.assertTrue((env.control/'too-big.part').exists())
        self.assertTrue((env.control/'too-big.json').exists())
        with self.assertRaises(ContractError):env.reserve_file('too-big','temporary/another.bin',4096)
        with self.assertRaises(RuntimeError):
            with env.reserve_file('raised','temporary/raised.bin',4096) as sink:
                sink.write(b'private partial');raise RuntimeError('fixture interruption')
        self.assertFalse((self.root/'temporary/raised.bin').exists())
        self.assertIn(b'private partial',(env.control/'raised.part').read_bytes())

    def test_no_sparse_fallback_after_actual_allocator_error(self):
        env=self.envelope()
        with patch('ygo_kito.storage_envelope.os.posix_fallocate',side_effect=OSError('fixture unavailable')):
            with self.assertRaises(OSError):env.reserve_file('allocator-error','state/failed.bin',4096)
        self.assertTrue((env.control/'allocator-error.json').exists())
        self.assertFalse((self.root/'state/failed.bin').exists())

    def test_concurrent_admission_cannot_sell_the_same_remaining_capacity_twice(self):
        block=os.statvfs(self.root).f_frsize;baseline=workspace_usage(self.root)['accounted_bytes']
        env=self.envelope(limit_bytes=baseline+24*block)
        env._initialize_control()  # Fixture setup avoids first-owner creation race.
        def acquire(index):
            try:
                sink=env.reserve_file('concurrent-'+str(index),'state/'+str(index)+'.bin',8*block)
                sink.close();return 'reserved'
            except StorageEnvelopeExceeded:return 'refused'
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(acquire,(1,2)))
        self.assertEqual(sorted(result),['refused','reserved'])
        self.assertLess(env.audit()['conservative_accounted_total_bytes'],env.limit_bytes)

    def test_hardlinks_do_not_double_charge_real_inode_and_symlinks_are_never_followed(self):
        file=self.root/'state/a';file.write_bytes(b'abc')
        before=workspace_usage(self.root)
        os.link(file,self.root/'state/b')
        after=workspace_usage(self.root)
        self.assertEqual(before['inode_count'],after['inode_count'])
        with tempfile.TemporaryDirectory() as outside:
            secret=Path(outside)/'not-to-be-read';secret.write_bytes(b'outside payload')
            (self.root/'state/link').symlink_to(secret)
            self.assertEqual(workspace_usage(self.root)['symlink_objects_not_followed'],1)
            with self.assertRaises(ContractError):self.envelope().reserve_file('alias','state/link',4096)

    def test_scope_escape_symlink_parent_and_unknown_user_control_directory_are_refused(self):
        env=self.envelope()
        with self.assertRaises(ContractError):env.reserve_file('outside','../escape',4096)
        with self.assertRaises(ContractError):env.reserve_file('scope','other.bin',4096)
        (self.root/'state/alias').symlink_to(self.root/'temporary',target_is_directory=True)
        with self.assertRaises(ContractError):env.reserve_file('alias','state/alias/new',4096)
        env.control.mkdir(parents=True);(env.control/'user-data').write_text('untouched')
        with self.assertRaises(ContractError):env.reserve_file('unowned','state/unowned',4096)
        self.assertEqual((env.control/'user-data').read_text(),'untouched')

    def test_external_growth_free_space_and_mutated_policy_stop_future_writes(self):
        env=self.envelope(limit_bytes=256*1024)
        with env.reserve_file('growing','state/out',4096) as sink:
            (self.root/'temporary/uncontrolled').write_bytes(b'u'*(256*1024))
            # Unwrapped growth is outside sink enforcement; a full explicit
            # boundary guard detects it and stops publication/continuation.
            with self.assertRaises(StorageEnvelopeExceeded):sink.flush()
        self.assertFalse((self.root/'state/out').exists())
        env=self.envelope()
        with patch('ygo_kito.storage_envelope.shutil.disk_usage',return_value=type('Disk',(),{'free':0})()):
            with self.assertRaises(StorageEnvelopeExceeded):env.guard(1)
        env.limit_bytes+=1
        with self.assertRaises(ContractError):env.audit()

    def test_receipt_or_inode_tamper_and_late_existing_destination_fail_closed(self):
        env=self.envelope()
        with env.reserve_file('record','state/record',4096) as sink:
            sink.record.write_text('{}')
            with self.assertRaises(ContractError):sink.write(b'changed')
        with env.reserve_file('late','state/late',4096) as sink:
            sink.write(b'our new payload')
            (self.root/'state/late').write_bytes(b'user arrived later')
            with self.assertRaises(ContractError):sink.commit()
        self.assertEqual((self.root/'state/late').read_bytes(),b'user arrived later')
        self.assertTrue((env.control/'late.part').exists())

    def test_cli_default_is_read_only_and_never_claims_full_writer_or_completion_coverage(self):
        before=set(self.root.rglob('*'));output=io.StringIO()
        with redirect_stdout(output):code=main(['--workspace',str(self.root)])
        self.assertEqual(code,0);report=json.loads(output.getvalue())
        self.assertFalse(report['whole_workspace_write_enforcement_verified'])
        self.assertFalse(report['minimum_training_volume_completion_verified'])
        self.assertIn('existing_SQLite_transactions_until_integrated',report['remaining_uncontrolled_writers'])
        self.assertEqual(set(self.root.rglob('*')),before)

    def test_actual_small_tensor_serialization_uses_preallocated_sink_without_training(self):
        import torch
        env=self.envelope()
        with env.reserve_file('tensor','state/tiny.weights',16*1024) as sink:
            torch.save({'kind':'tiny-contract-only','tensor':torch.arange(4)},sink)
            receipt=sink.commit()
        self.assertLess(receipt['artifact_bytes'],16*1024)
        loaded=torch.load(self.root/'state/tiny.weights',map_location='cpu',weights_only=True)
        self.assertTrue(torch.equal(loaded['tensor'],torch.arange(4)))
        self.assertFalse(env.audit()['minimum_training_volume_completion_verified'])

    def test_missing_controlled_roots_and_unreadable_inventory_never_report_ready(self):
        env=StorageEnvelope(self.root,state_roots=['missing-state'],outside_bytes=0,min_free_bytes=0,safety_margin_bytes=0)
        self.assertFalse(env.audit()['controlled_new_file_sink_ready'])
        def broken(*args,**kwargs):
            kwargs['onerror'](PermissionError('fixture inaccessible directory'))
            return iter(())
        with patch('ygo_kito.storage_envelope.os.walk',side_effect=broken):
            with self.assertRaises(PermissionError):env.audit()

    def test_memoryview_limit_counts_bytes_not_elements_and_truncation_erases_old_tail(self):
        env=self.envelope()
        with env.reserve_file('view','state/view',4) as sink:
            payload=memoryview(bytearray(8)).cast('I')
            self.assertEqual(len(payload),2);self.assertEqual(payload.nbytes,8)
            with self.assertRaises(StorageEnvelopeExceeded):sink.write(payload)
            self.assertEqual(sink.part.stat().st_size,4)
        with env.reserve_file('truncate','state/truncate',4096) as sink:
            sink.write(b'private-old-tail');sink.truncate(1);sink.seek(4);sink.write(b'Z')
            sink.commit()
        self.assertEqual((self.root/'state/truncate').read_bytes(),b'p\0\0\0Z')


if __name__=='__main__':unittest.main()
