"""Isolated inert package files; never edits production source or imports them."""
from pathlib import Path
import tempfile
import unittest

from ygo_kito.implementation_identity import source_tree_snapshot, assert_source_tree
from ygo_kito.validation import ContractError


class ImplementationIdentityTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        (self.root/'__init__.py').write_text('# inert fixture\n')
        for name in ('left/codec.py','right/codec.py'):
            path=self.root/name;path.parent.mkdir();path.write_text('# identical bytes, different modules\n')

    def test_canonical_relative_names_preserve_same_basename_submodules(self):
        first=source_tree_snapshot(self.root)
        self.assertEqual(set(first),{'__init__.py','left/codec.py','right/codec.py'})
        self.assertEqual(first['left/codec.py'],first['right/codec.py'])
        assert_source_tree(self.root,first)

    def test_change_add_or_delete_invalidates_old_driver_source_identity(self):
        expected=source_tree_snapshot(self.root)
        original=(self.root/'left/codec.py').read_bytes()
        (self.root/'left/codec.py').write_bytes(b'# changed fixture\n')
        with self.assertRaises(ContractError):assert_source_tree(self.root,expected)
        (self.root/'left/codec.py').write_bytes(original)
        extra=self.root/'new_helper.py';extra.write_text('# new fixture\n')
        with self.assertRaises(ContractError):assert_source_tree(self.root,expected)
        extra.unlink();(self.root/'right/codec.py').unlink()
        with self.assertRaises(ContractError):assert_source_tree(self.root,expected)

    def test_cache_files_do_not_change_identity_and_source_links_are_rejected(self):
        expected=source_tree_snapshot(self.root)
        (self.root/'__pycache__').mkdir();(self.root/'__pycache__/fixture.pyc').write_bytes(b'not source')
        assert_source_tree(self.root,expected)
        (self.root/'linked.py').symlink_to(self.root/'left/codec.py')
        with self.assertRaises(ContractError):source_tree_snapshot(self.root)


if __name__=='__main__':unittest.main()
