"""Public metadata projection only; no native calls or fault experiments."""
from dataclasses import asdict
from types import SimpleNamespace
import unittest

from ygo_kito.native_protocol import Reader
from ygo_kito.public_history import consume


class PublicShufflePrivacyTests(unittest.TestCase):
    def project(self, old, new):
        engine = SimpleNamespace(_public_history=[], _known_owners={}, _overlay_owners={})
        # This metadata hook clears optional material memory if present.
        reader = Reader(bytes((8, len(old))) + b"".join(old) + b"".join(new))
        consume(engine, 36, reader, {})
        self.assertEqual(reader.offset, len(reader.data))
        return [asdict(event) for event in engine._public_history]

    def test_shuffle_packet_old_order_does_not_reveal_its_random_permutation(self):
        left, right = bytes((0,8,1,8)), bytes((0,8,4,8))
        first = self.project((left, right), (right, left))
        second = self.project((right, left), (right, left))
        self.assertEqual(first, second)
        self.assertEqual([v['sequence'] for v in first[0]['details']['locations']], [1,4])

    def test_private_destinations_do_not_change_public_shuffle_metadata(self):
        old = (bytes((1,8,0,8)), bytes((1,8,3,8)))
        first = self.project(old, tuple(reversed(old)))
        second = self.project(old, (bytes((1,8,2,8)), bytes((1,8,7,8))))
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
