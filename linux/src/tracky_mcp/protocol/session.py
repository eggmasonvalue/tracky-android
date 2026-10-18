"""Pure protocol session state machine for the observed CS10B handshake.

``ScaleSession`` accepts raw RX frames and returns decoded events plus the
bytes that a transport may write.  It does not know about bleak, GATT handles,
or notification callbacks; those belong in ``tracky_mcp.ble``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .burst import BurstAssembler, OpaqueBurst
from .decode import (
    DecodedFrame,
    InfoFrame,
    MeasurementFrame,
    StatusFrame,
    decode_frame,
)
from .frames import (
    Opcode,
    WeightUnit,
    build_a0_writes,
    build_over_cmd,
    build_time_push,
    build_time_sync,
    build_unit_config,
    qn_epoch_from_datetime,
    qn_epoch_from_unix,
)


class SessionState(Enum):
    """Handshake phases after notifications have been enabled by the caller."""

    WAITING_INFO = "waiting_info"
    WAITING_14 = "waiting_0x14"
    WAITING_21 = "waiting_0x21"
    LIVE = "live"


ClockValue = datetime | int | float
Clock = Callable[[], ClockValue]


@dataclass(slots=True)
class SessionOutput:
    """Result of feeding one RX frame into a :class:`ScaleSession`."""

    tx_writes: list[bytes]
    events: list[DecodedFrame]
    state: SessionState


def _qn_epoch_from_clock_value(value: ClockValue) -> int:
    if isinstance(value, datetime):
        return qn_epoch_from_datetime(value)
    return qn_epoch_from_unix(value)


class ScaleSession:
    """Drive the fixture-backed handshake without owning a BLE transport.

    A new instance represents a connection whose notifications are already
    enabled and is therefore initially waiting for ``0x12`` info.  Time values
    are supplied at the boundary as QN-epoch seconds.  Inject ``clock`` (which
    returns a Unix timestamp or datetime) for deterministic tests, or pass a
    fixed ``qn_epoch_seconds`` for replaying a capture exactly.
    """

    def __init__(
        self,
        *,
        unit_byte: int | WeightUnit = WeightUnit.KG,
        clock: Clock | None = None,
        qn_epoch_seconds: int | None = None,
    ) -> None:
        self.unit_byte = int(unit_byte)
        if not 0 <= self.unit_byte <= 0xFF:
            raise ValueError("unit_byte must be an unsigned byte")
        self._clock = clock or time.time
        self._fixed_qn_epoch_seconds = qn_epoch_seconds
        self.state = SessionState.WAITING_INFO
        self.protocol_type: int | None = None
        self.configured = False
        self.received_events: list[DecodedFrame] = []
        self.measurements: list[MeasurementFrame] = []
        self._burst_assembler = BurstAssembler()
        self.bursts: list[OpaqueBurst] = self._burst_assembler.completed

    @property
    def waiting_for_info(self) -> bool:
        return self.state is SessionState.WAITING_INFO

    @property
    def notifications_enabled(self) -> bool:
        """The protocol starts after the BLE layer has enabled notifications."""

        return True

    def _qn_epoch_seconds(self, override: int | None, now: ClockValue | None) -> int:
        if override is not None and now is not None:
            raise TypeError("pass qn_epoch_seconds or now, not both")
        if override is not None:
            return override
        if now is not None:
            return _qn_epoch_from_clock_value(now)
        if self._fixed_qn_epoch_seconds is not None:
            return self._fixed_qn_epoch_seconds
        return _qn_epoch_from_clock_value(self._clock())

    def feed(
        self,
        frame: bytes | bytearray | memoryview | str,
        *,
        qn_epoch_seconds: int | None = None,
        now: ClockValue | None = None,
    ) -> SessionOutput:
        """Feed one RX frame and return its event plus any immediate writes.

        Known frames with a bad checksum are still returned as events for
        diagnostics, but cannot advance the handshake or be recorded as live
        measurements.  Repeated valid ``0x10`` frames are emitted one at a time
        and accumulated in :attr:`measurements`.
        """

        decoded = decode_frame(frame)
        self.received_events.append(decoded)
        writes: list[bytes] = []

        if decoded.checksum_valid is False:
            self._burst_assembler.interrupt()
            return SessionOutput(tx_writes=writes, events=[decoded], state=self.state)

        if not isinstance(decoded, MeasurementFrame):
            self._burst_assembler.interrupt()

        if isinstance(decoded, InfoFrame) and self.state is SessionState.WAITING_INFO:
            self.protocol_type = decoded.protocol_type
            epoch = self._qn_epoch_seconds(qn_epoch_seconds, now)
            writes.extend(
                (
                    build_unit_config(self.protocol_type, self.unit_byte),
                    build_time_push(epoch),
                )
            )
            self.configured = True
            self.state = SessionState.WAITING_14

        elif (
            isinstance(decoded, StatusFrame)
            and decoded.opcode == Opcode.STATUS_14
            and self.state is SessionState.WAITING_14
        ):
            protocol_type = self.protocol_type
            if protocol_type is None:
                protocol_type = decoded.protocol_type
                self.protocol_type = protocol_type
            epoch = self._qn_epoch_seconds(qn_epoch_seconds, now)
            writes.append(build_time_sync(protocol_type, epoch))
            self.state = SessionState.WAITING_21

        elif (
            isinstance(decoded, StatusFrame)
            and decoded.opcode == Opcode.STATUS_21
            and self.state is SessionState.WAITING_21
        ):
            writes.extend(build_a0_writes())
            self.state = SessionState.LIVE

        elif isinstance(decoded, MeasurementFrame):
            self.measurements.append(decoded)
            if decoded.b5 == 0x01 and decoded.b6 == 0x21:
                protocol_type = self.protocol_type or decoded.protocol_type
                writes.append(build_over_cmd(protocol_type, 0x10, b6=0x21))
            self._burst_assembler.add(decoded)

        return SessionOutput(tx_writes=writes, events=[decoded], state=self.state)

    def feed_many(
        self,
        frames: Iterable[bytes | bytearray | memoryview | str],
        *,
        qn_epoch_seconds: int | None = None,
    ) -> list[SessionOutput]:
        """Replay frames in order, returning one output per input frame."""

        return [self.feed(frame, qn_epoch_seconds=qn_epoch_seconds) for frame in frames]

    def reset(self) -> None:
        """Reset handshake state for a new connection while retaining options."""

        self.state = SessionState.WAITING_INFO
        self.protocol_type = None
        self.configured = False
        self.received_events.clear()
        self.measurements.clear()
        self._burst_assembler.reset()


__all__ = [
    "Clock",
    "ClockValue",
    "ScaleSession",
    "SessionOutput",
    "SessionState",
]
