"""Boundary checks for the buffer handed to the pinned core's ``set_responseb``.

Layer 1 is ordinary unit work: the guard's encoding bound, padding and refusals.
Layer 2 is an isolated memory-boundary experiment that reproduces the original
out-of-bounds read without the rule core.  It runs the faulting read in a child
process, because the defect's defining property is that it terminates whichever
process performs the read; a crash there is the expected observation, not a
failure of the engine.

None of this is real-duel evidence: no rule core is loaded anywhere in this
module, so nothing here shows a native game or a policy decision working.
"""

import ast
import ctypes as C
from pathlib import Path
import subprocess
import sys
import unittest

from ygo_kito.native_protocol import NativeError
from ygo_kito.native_response_guard import (
    CORE_RESPONSE_READ_BYTES, MAX_RESPONSE_BYTES, MAX_SELECTION_INDICES, PADDING_BYTE,
    assert_core_read_fits, build_response_buffer, capacity, check_response, describe,
)

SOURCE = Path(__file__).resolve().parents[1] / "src/ygo_kito/native.py"

# Child program for the isolated experiment.  It maps two pages, makes the
# second unreadable, places a buffer of the requested size so that its last
# byte is the last byte before that unreadable page, then performs the
# requested read.  Printing DONE is reachable only when every read byte stayed
# inside the readable page.
CHILD = r'''
import ctypes, mmap, os, sys

PAGE_READWRITE, PAGE_NOACCESS = 0x04, 0x01
MEM_COMMIT, MEM_RESERVE = 0x1000, 0x2000


def guarded_end(size):
    page = mmap.PAGESIZE
    keep = None
    if os.name == "nt":
        k32 = ctypes.windll.kernel32
        k32.VirtualAlloc.restype = ctypes.c_void_p
        k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
        base = k32.VirtualAlloc(None, ctypes.c_size_t(page * 2), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not base:
            raise SystemExit("alloc failed")
        old = ctypes.c_uint32()
        k32.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32,
                                       ctypes.POINTER(ctypes.c_uint32)]
        if not k32.VirtualProtect(ctypes.c_void_p(base + page), ctypes.c_size_t(page), PAGE_NOACCESS,
                                  ctypes.byref(old)):
            raise SystemExit("protect failed")
    else:
        keep = mmap.mmap(-1, page * 2)
        base = ctypes.addressof(ctypes.c_char.from_buffer(keep))
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.mprotect(ctypes.c_void_p(base + page), ctypes.c_size_t(page), 0) != 0:
            raise SystemExit("mprotect failed")
    return ctypes.c_void_p(base + page - size), keep


size, read = int(sys.argv[1]), int(sys.argv[2])
pointer, _keep = guarded_end(size)
ctypes.memset(pointer, 0, size)
observed = ctypes.string_at(pointer, read)
sys.stdout.write("DONE %d\n" % len(observed))
sys.stdout.flush()
'''


def run_child(size, read):
    """Run the boundary experiment out of process; returns (returncode, stdout)."""
    finished = subprocess.run([sys.executable, "-c", CHILD, str(size), str(read)],
                              capture_output=True, text=True, timeout=120)
    return finished.returncode, finished.stdout


class ResponseEncodingTests(unittest.TestCase):
    def test_encoding_bound_is_the_documented_selection_ceiling(self):
        self.assertEqual(MAX_SELECTION_INDICES, 63)
        self.assertEqual(MAX_RESPONSE_BYTES, 1 + MAX_SELECTION_INDICES)
        # The core reads more than the adapter can ever encode.  If these ever
        # cross, one of the two assumptions moved and the guard must be re-pinned
        # against the core it claims to describe.
        self.assertGreater(CORE_RESPONSE_READ_BYTES, MAX_RESPONSE_BYTES)

    def test_payload_starts_at_offset_zero_and_the_allocation_is_core_sized(self):
        for payload in (b"\x00", b"\x01\x07", bytes(range(1, MAX_RESPONSE_BYTES))):
            with self.subTest(length=len(payload)):
                buffer = build_response_buffer(payload)
                self.assertEqual(capacity(buffer), CORE_RESPONSE_READ_BYTES)
                self.assertEqual(bytes(buffer[:len(payload)]), payload)

    def test_the_core_record_read_stays_inside_the_allocation(self):
        payload = b"\x03\x01\x02\x03"
        buffer = build_response_buffer(payload)
        self.assertGreaterEqual(capacity(buffer), CORE_RESPONSE_READ_BYTES)
        observed = C.string_at(C.addressof(buffer), CORE_RESPONSE_READ_BYTES)
        self.assertEqual(len(observed), CORE_RESPONSE_READ_BYTES)
        self.assertEqual(observed[:len(payload)], payload)
        self.assertEqual(observed[len(payload):],
                         bytes([PADDING_BYTE]) * (CORE_RESPONSE_READ_BYTES - len(payload)))

    def test_padding_is_explicit_zero_rather_than_stale_memory(self):
        for length in (1, MAX_RESPONSE_BYTES):
            buffer = build_response_buffer(bytes([0xff]) * length)
            self.assertEqual(bytes(buffer[length:]), b"\x00" * (CORE_RESPONSE_READ_BYTES - length))

    def test_oversize_response_is_refused_instead_of_truncated(self):
        with self.assertRaisesRegex(NativeError, "exceeds"):
            check_response(b"\x00" * (MAX_RESPONSE_BYTES + 1))
        with self.assertRaisesRegex(NativeError, "exceeds"):
            build_response_buffer(b"\x00" * (MAX_RESPONSE_BYTES + 1))

    def test_empty_or_non_bytes_response_is_refused(self):
        with self.assertRaisesRegex(NativeError, "empty"):
            check_response(b"")
        for value in (0, -1, None, "0102", (1, 2)):
            with self.subTest(value=value), self.assertRaisesRegex(NativeError, "must be bytes"):
                check_response(value)

    def test_bytearray_and_memoryview_carry_the_same_payload(self):
        self.assertEqual(bytes(build_response_buffer(bytearray(b"\x02\x05\x09"))[:3]), b"\x02\x05\x09")
        self.assertEqual(bytes(build_response_buffer(memoryview(b"\x02\x05"))[:2]), b"\x02\x05")

    def test_a_buffer_sized_only_to_the_encoding_is_refused(self):
        # This is exactly the shipped defect: long enough for the payload,
        # shorter than the record the core reads out of it.
        undersized = (C.c_uint8 * MAX_RESPONSE_BYTES)()
        with self.assertRaisesRegex(NativeError, "out-of-bounds"):
            assert_core_read_fits(undersized)
        guarded = build_response_buffer(b"\x01\x02")
        self.assertEqual(capacity(assert_core_read_fits(guarded)), CORE_RESPONSE_READ_BYTES)

    def test_describe_reports_the_pinned_contract(self):
        self.assertEqual(describe(), {"max_selection_indices": 63, "max_response_bytes": 64,
                                      "core_response_read_bytes": 256, "padding_byte": 0})


class IsolatedBoundaryExperimentTests(unittest.TestCase):
    """The original defect, reproduced and then disproved, without the core."""

    def test_the_core_record_read_completes_on_a_core_sized_allocation(self):
        code, out = run_child(CORE_RESPONSE_READ_BYTES, CORE_RESPONSE_READ_BYTES)
        self.assertEqual(code, 0, f"a 256-byte allocation must survive the core read (code {code}): {out!r}")
        self.assertIn(f"DONE {CORE_RESPONSE_READ_BYTES}", out)

    def test_the_encoding_sized_allocation_faults_when_the_core_reads_it(self):
        # 64 bytes is everything the adapter can encode, and it is still short
        # of the core's fixed read.  Abutting an unreadable page turns that
        # over-read into the fault class the historical SIGSEGV belongs to.
        code, out = run_child(MAX_RESPONSE_BYTES, CORE_RESPONSE_READ_BYTES)
        self.assertNotEqual(code, 0, "a 64-byte response buffer must not survive a 256-byte core read")
        self.assertNotIn("DONE", out)

    def test_the_harness_discriminates_rather_than_failing_everything(self):
        # Control: the same guarded allocation succeeds when the read is small
        # enough, so a non-zero exit above means over-read, not a broken harness.
        code, out = run_child(CORE_RESPONSE_READ_BYTES, MAX_RESPONSE_BYTES)
        self.assertEqual(code, 0)
        self.assertIn(f"DONE {MAX_RESPONSE_BYTES}", out)


class ResponseCallSiteTests(unittest.TestCase):
    """Static guard so a future call site cannot reintroduce the short buffer."""

    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    @staticmethod
    def _guard_assignments(function):
        """Names inside ``function`` bound to a build_response_buffer(...) call."""
        names = {}
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                target = node.value.func
                if isinstance(target, ast.Name) and target.id == "build_response_buffer":
                    for store in node.targets:
                        if isinstance(store, ast.Name):
                            names[store.id] = node
        return names

    def test_every_set_responseb_call_hands_over_a_guard_buffer(self):
        calls = []
        for function in [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)]:
            found = [n for n in ast.walk(function)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "set_responseb"]
            if found:
                calls.extend((function, n) for n in found)
        self.assertTrue(calls, "native.py no longer calls set_responseb; retire this guard test")
        for function, node in calls:
            with self.subTest(line=node.lineno, function=function.name):
                self.assertEqual(len(node.args), 2, "set_responseb takes the duel and one buffer")
                argument = node.args[1]
                if isinstance(argument, ast.Call):
                    self.assertIsInstance(argument.func, ast.Name)
                    self.assertEqual(argument.func.id, "build_response_buffer")
                else:
                    # A named local is allowed, but it must be the guard's buffer,
                    # because the allocation has to outlive the call.
                    self.assertIsInstance(argument, ast.Name, "unnamed response buffer expression")
                    assignments = self._guard_assignments(function)
                    self.assertIn(argument.id, assignments,
                                  "response buffer must come from build_response_buffer(...)")

    def test_the_response_call_site_allocates_no_byte_array_of_its_own(self):
        for function in [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)]:
            calls = [n for n in ast.walk(function)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "set_responseb"]
            if not calls:
                continue
            with self.subTest(function=function.name):
                allocations = [n for n in ast.walk(function)
                               if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult)
                               and isinstance(n.right, ast.Constant) and isinstance(n.right.value, int)]
                self.assertEqual(allocations, [],
                                 "the response buffer must be sized by the guard, not locally")

    def test_the_guard_is_imported_by_name_so_the_ast_check_is_not_a_coincidence(self):
        # assertTrue, not assertIn: a failure must not echo the whole adapter.
        self.assertTrue("from .native_response_guard import build_response_buffer" in self.source,
                        "native.py must import the guard by name")


if __name__ == "__main__":
    unittest.main()
