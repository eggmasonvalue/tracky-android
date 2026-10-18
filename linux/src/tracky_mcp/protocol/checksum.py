"""Checksum helpers for the captured CS10B protocol.

The frames observed on the FFF1/FFF2 path use an additive, one-byte trailer:
``sum(frame_without_trailer) & 0xff``.  The short ``time_push`` command is an
intentional exception and must not be passed to :func:`append_checksum` when
constructing that command.
"""

from __future__ import annotations

from collections.abc import Iterable

ByteInput = bytes | bytearray | memoryview | Iterable[int]


def _as_bytes(data: ByteInput) -> bytes:
    """Return *data* as bytes while keeping checksum inputs easy to test."""

    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)
    return bytes(data)


def checksum(data: ByteInput) -> int:
    """Calculate the protocol's additive checksum for a frame body.

    ``data`` is the portion before the checksum byte.  The returned value is
    always in the range 0..255.
    """

    return sum(_as_bytes(data)) & 0xFF


def append_checksum(data: ByteInput) -> bytes:
    """Return a copy of *data* with its checksum byte appended."""

    body = _as_bytes(data)
    return body + bytes((checksum(body),))


def has_valid_checksum(frame: ByteInput) -> bool:
    """Return whether the final byte matches the additive checksum.

    This helper intentionally does not decide whether a particular opcode is
    checksum-bearing.  Callers that know the frame type should use this helper
    for those frames and treat the short ``0x02`` time-push command separately.
    """

    value = _as_bytes(frame)
    return bool(value) and checksum(value[:-1]) == value[-1]


__all__ = [
    "append_checksum",
    "checksum",
    "has_valid_checksum",
]
