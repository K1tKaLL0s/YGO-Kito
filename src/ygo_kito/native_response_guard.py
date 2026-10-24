"""Capacity contract for the buffer handed to the pinned core's ``set_responseb``.

``set_responseb`` takes a bare pointer, never a length.  The pinned core reads a
fixed-size response record out of that pointer, while the adapter encodes a much
shorter selection payload into it.  A buffer sized to the *encoding* therefore
leaves the core reading past the end of the allocation: an out-of-bounds read
inside native code that Python cannot observe, and that only faults when the
allocation happens to end against an unreadable page.

This module is the single place that knows both sizes:

``MAX_RESPONSE_BYTES``
    The longest response the adapter can encode: one selection-count byte plus
    at most ``MAX_SELECTION_INDICES`` index bytes.  Every selection codec pins
    that ceiling (``decode_deck_choices`` requires ``maximum <= min(count, 63)``
    and the kind 15/20 enumerators cap ``top`` at 63), so 64 bytes is the whole
    encoding space, not a guess.

``CORE_RESPONSE_READ_BYTES``
    The fixed record the pinned core reads from the pointer regardless of the
    encoded length.  This is established from the pinned core's own source (see
    the constant's docstring), not from the handover's summary of it, and it is
    confirmed independently by the isolation experiment in
    ``tests/test_native_response_buffer.py``: a 64-byte allocation abutting an
    unreadable page faults, while a 256-byte allocation returns normally.

A payload longer than ``MAX_RESPONSE_BYTES`` is refused rather than truncated:
silently shortening a selection would submit a different action than the model
chose, so this fails closed like every other unsupported native shape.
"""

import ctypes as C

from .native_protocol import NativeError

MAX_SELECTION_INDICES = 63
"""Largest index count any codec can encode into one selection response.

Corroborated by the three codecs that build byte responses, each of which refuses
to emit more than 63 indices: ``native_protocol`` (kind 15/20 enumeration),
``private_selection`` and ``sum_protocol``.  A payload longer than that cannot
reach this module from the current decoders.
"""

MAX_RESPONSE_BYTES = 1 + MAX_SELECTION_INDICES
"""Longest encodable response: the count byte plus its indices.

``sum_protocol`` names this same width in its own comment ("Never silently drop
core-offered combinations outside the 64-byte response"), so the bound is the
project's documented encoding width, not a guess made here.
"""

CORE_RESPONSE_READ_BYTES = 256
"""Fixed record the pinned core reads from the ``set_responseb`` pointer.

Verified in the pinned core source rather than inferred from a report.  At
``Fluorohydride/ygopro-core@3209cd866a55e8501a0ed358d3064d9ae0ae6b30``:

* ``common.h``  -- ``#define SIZE_RETURN_VALUE 256u``
* ``field.h``   -- ``union return_value { uint8_t bvalue[SIZE_RETURN_VALUE]; ... }``
* ``duel.cpp``  -- ``void duel::set_responseb(byte* resp) {
  std::memcpy(game_field->returns.bvalue, resp, SIZE_RETURN_VALUE); }``
* ``ocgapi.h``  -- ``void set_responseb(intptr_t pduel, byte* buf);`` (no length)
* ``ocgapi.cpp``-- forwards straight to ``duel::set_responseb(buf)``.

The copy is an unconditional ``memcpy`` of 256 bytes out of the caller's pointer,
so a shorter allocation is an out-of-bounds read inside the core.  It completes
synchronously; the core keeps no pointer to our buffer.
"""

PADDING_BYTE = 0
"""Bytes past the payload are read by the core; supply zeros, not leftovers."""


def check_response(payload):
    """Return ``payload`` as bytes, refusing anything the core would misread."""
    if isinstance(payload, (bytearray, memoryview)):
        payload = bytes(payload)
    if not isinstance(payload, bytes):
        raise NativeError(f"native response must be bytes, not {type(payload).__name__}")
    if not payload:
        raise NativeError("native response is empty; a selection always encodes a count byte")
    if len(payload) > MAX_RESPONSE_BYTES:
        raise NativeError(
            f"native response of {len(payload)} bytes exceeds the {MAX_RESPONSE_BYTES}-byte "
            "selection encoding; refusing to truncate a submitted action"
        )
    return payload


def build_response_buffer(payload):
    """Build a core-readable buffer holding ``payload`` at offset 0.

    The returned array is ``CORE_RESPONSE_READ_BYTES`` long and zero padded, so
    the core's fixed read stays inside the allocation.  The caller must keep the
    object alive until ``set_responseb`` has returned; the core copies out of it
    synchronously, it never takes ownership of the pointer.
    """
    payload = check_response(payload)
    buffer = (C.c_uint8 * CORE_RESPONSE_READ_BYTES)()
    buffer[:len(payload)] = payload
    # Slicing a ctypes array yields a list of ints, so compare as bytes.
    padding = bytes(buffer[len(payload):])
    if padding != bytes([PADDING_BYTE]) * (CORE_RESPONSE_READ_BYTES - len(payload)):
        raise NativeError("native response buffer padding is not zero")
    return buffer


def capacity(buffer):
    """Return the number of bytes the core may read from ``buffer``."""
    try:
        return len(buffer)
    except TypeError as error:
        raise NativeError("native response buffer must be a sized ctypes array") from error


def assert_core_read_fits(buffer):
    """Refuse a buffer the core's fixed record read would run past."""
    size = capacity(buffer)
    if size < CORE_RESPONSE_READ_BYTES:
        raise NativeError(
            f"native response buffer holds {size} bytes but the pinned core reads "
            f"{CORE_RESPONSE_READ_BYTES}; this is the out-of-bounds read the guard exists to prevent"
        )
    return buffer


def describe():
    """Return the pinned contract for receipts and audits."""
    return {"max_selection_indices": MAX_SELECTION_INDICES,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "core_response_read_bytes": CORE_RESPONSE_READ_BYTES,
            "padding_byte": PADDING_BYTE}
