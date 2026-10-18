"""Constants and typed builders for the observed CS10B wire writes.

This module contains only protocol bytes.  It deliberately has no BLE or
transport dependency, so a caller can inspect or test every write before it is
handed to a client.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from enum import IntEnum

from .checksum import append_checksum

# Seconds between the Unix epoch and the QN epoch (2000-01-01 UTC).
QN_EPOCH_UNIX = 946_684_800


class Opcode(IntEnum):
    """Opcodes observed in the sanitized CS10B session."""

    MEASUREMENT = 0x10
    INFO = 0x12
    UNIT_CONFIG = 0x13
    STATUS_14 = 0x14
    TIME_PUSH = 0x02
    TIME_SYNC = 0x20
    STATUS_21 = 0x21
    OVER = 0x1F
    A0 = 0xA0


class WeightUnit(IntEnum):
    """Unit selector values observed in the unit configuration command."""

    KG = 0x01
    LB = 0x02


# These are the checksum-bearing opcodes seen in the fixture.  ``TIME_PUSH``
# is intentionally absent: its five-byte form has no additive trailer.
CHECKSUM_BEARING_OPCODES = frozenset(
    {
        Opcode.MEASUREMENT,
        Opcode.INFO,
        Opcode.UNIT_CONFIG,
        Opcode.STATUS_14,
        Opcode.TIME_SYNC,
        Opcode.STATUS_21,
        Opcode.OVER,
        Opcode.A0,
    }
)


def _byte(value: int, *, name: str) -> int:
    value = int(value)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be an unsigned byte, got {value}")
    return value


def _u32(value: int, *, name: str = "epoch") -> int:
    value = int(value)
    if not 0 <= value <= 0xFFFF_FFFF:
        raise ValueError(f"{name} must fit in an unsigned 32-bit value, got {value}")
    return value


def _resolve_epoch(
    qn_epoch_seconds: int | None,
    epoch_seconds: int | None,
) -> int:
    if qn_epoch_seconds is not None and epoch_seconds is not None:
        raise TypeError("pass qn_epoch_seconds or epoch_seconds, not both")
    if epoch_seconds is not None:
        qn_epoch_seconds = epoch_seconds
    if qn_epoch_seconds is None:
        qn_epoch_seconds = int(time.time()) - QN_EPOCH_UNIX
    return _u32(qn_epoch_seconds, name="QN epoch seconds")


def qn_epoch_from_unix(value: int | float) -> int:
    """Convert a Unix timestamp to whole seconds from the QN epoch."""

    return _u32(int(value) - QN_EPOCH_UNIX, name="QN epoch seconds")


def qn_epoch_from_datetime(value: datetime) -> int:
    """Convert an aware (or UTC-assumed naive) datetime to QN seconds."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return _u32(int(value.timestamp()) - QN_EPOCH_UNIX, name="QN epoch seconds")


def build_unit_config(
    protocol_type: int = 0x20,
    unit_byte: int | WeightUnit = WeightUnit.KG,
    *,
    unit: int | WeightUnit | None = None,
) -> bytes:
    """Build the observed ``0x13`` unit configuration write.

    The fixture requested pounds with ``unit_byte=0x02``.  The default is the
    explicit kilogram selector; callers should choose the requested display
    unit rather than relying on an implicit conversion in the decoder.
    """

    if unit is not None:
        unit_byte = unit
    body = bytes(
        (
            Opcode.UNIT_CONFIG,
            0x09,
            _byte(protocol_type, name="protocol_type"),
            _byte(unit_byte, name="unit_byte"),
            0x10,
            0x00,
            0x00,
            0x00,
        )
    )
    return append_checksum(body)


def build_time_push(
    qn_epoch_seconds: int | None = None,
    *,
    epoch_seconds: int | None = None,
) -> bytes:
    """Build the short, non-checksummed ``time_push`` command (opcode 0x02).

    The argument is seconds since 2000-01-01 UTC, matching the captured wire
    representation.  If omitted, the current Unix time is converted at the
    boundary.  This five-byte command is the documented checksum exception.
    """

    epoch = _resolve_epoch(qn_epoch_seconds, epoch_seconds)
    return bytes((Opcode.TIME_PUSH,)) + epoch.to_bytes(4, "little")


def build_time_sync(
    protocol_type: int = 0x20,
    qn_epoch_seconds: int | None = None,
    *,
    epoch_seconds: int | None = None,
) -> bytes:
    """Build the checksummed ``0x20`` time synchronization write."""

    epoch = _resolve_epoch(qn_epoch_seconds, epoch_seconds)
    body = bytes(
        (
            Opcode.TIME_SYNC,
            0x08,
            _byte(protocol_type, name="protocol_type"),
        )
    ) + epoch.to_bytes(4, "little")
    return append_checksum(body)


def build_over_cmd(
    protocol_type: int = 0x20,
    data_type: int = 0x10,
    *,
    b6: int | None = 0x21,
) -> bytes:
    """Build the checksummed 0x1F CMD_OVER acknowledgment write.

    The scale requires this acknowledgment on FFF2 upon receiving Packet 1
    (b6=0x21) to release Packet 2 (b6=0x22). If b6 is omitted, the 5-byte
    legacy acknowledgment is emitted.
    """

    if b6 is not None:
        body = bytes(
            (
                Opcode.OVER,
                0x06,
                _byte(protocol_type, name="protocol_type"),
                _byte(data_type, name="data_type"),
                _byte(b6, name="b6"),
            )
        )
    else:
        body = bytes(
            (
                Opcode.OVER,
                0x05,
                _byte(protocol_type, name="protocol_type"),
                _byte(data_type, name="data_type"),
            )
        )
    return append_checksum(body)


def build_a0_1() -> bytes:
    """Build the first fixed ``0xA0`` session write from the capture."""

    body = bytes((Opcode.A0, 0x0D, 0x04, 0xFE, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    return append_checksum(body[:-1])


def build_a0_2() -> bytes:
    """Build the second fixed ``0xA0`` session write from the capture."""

    body = bytes(
        (Opcode.A0, 0x0D, 0x02, 0x01, 0x00, 0x08, 0x00, 0x21, 0x06, 0xB8, 0x04, 0x02, 0x00)
    )
    return append_checksum(body[:-1])


def build_a0_writes() -> list[bytes]:
    """Return the two fixed ``0xA0`` writes in capture order."""

    return [build_a0_1(), build_a0_2()]


__all__ = [
    "CHECKSUM_BEARING_OPCODES",
    "Opcode",
    "QN_EPOCH_UNIX",
    "WeightUnit",
    "build_a0_1",
    "build_a0_2",
    "build_a0_writes",
    "build_over_cmd",
    "build_time_push",
    "build_time_sync",
    "build_unit_config",
    "qn_epoch_from_datetime",
    "qn_epoch_from_unix",
]
