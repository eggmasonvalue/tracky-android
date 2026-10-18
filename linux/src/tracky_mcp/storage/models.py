"""Transport-independent records returned by local measurement storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from tracky_mcp.protocol import QUALITY_VERSION, MeasurementQuality


class SessionStatus(str, Enum):
    """Lifecycle of one locally recorded scale interaction."""

    OPEN = "open"
    COMPLETE = "complete"
    ABORTED = "aborted"


class OperationStatus(str, Enum):
    """Persisted lifecycle of one agent-visible acquisition operation."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AcquisitionOperation:
    """Explicit cross-call handle for a weigh-in acquisition."""

    id: str
    kind: str
    status: OperationStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    session_id: str | None
    error_code: str | None
    error_message: str | None
    metadata: dict[str, Any]

    @property
    def terminal(self) -> bool:
        return self.status in {
            OperationStatus.COMPLETE,
            OperationStatus.FAILED,
            OperationStatus.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class KnownDevice:
    """Agent-safe local identity for a discovered scale.

    The private BLE connection target is deliberately absent; callers resolve
    it through storage only when initiating a local transport operation.
    """

    id: str
    advertised_name: str | None
    alias: str | None
    model_label: str | None
    address_hash: str
    first_seen_at: datetime
    last_seen_at: datetime
    advertised_service_uuids: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DeviceConnection:
    """Private connection target paired with its agent-safe identity."""

    device: KnownDevice
    target: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class StoredMeasurement:
    """Captured interpretation of one measurement frame.

    The integer wire value and divisor remain authoritative. ``weight_kg`` is
    calculated with :class:`~decimal.Decimal` rather than persisted as a
    binary float.
    """

    protocol_type: int
    weight_raw_u16_be: int
    weight_scale_divisor: int
    weight_unit: str
    weight_formula: str
    weight_provenance: str
    b5: int
    b6: int
    word_block: tuple[int, ...]
    word_layout: str | None
    word_provenance: str
    opaque_unit_evidence: str | None

    @property
    def weight_kg(self) -> Decimal:
        return Decimal(self.weight_raw_u16_be) / Decimal(self.weight_scale_divisor)


@dataclass(frozen=True, slots=True)
class StoredFrame:
    """One losslessly retained wire frame and its captured interpretation."""

    session_id: str
    sequence: int
    observed_at: datetime | None
    elapsed_ms: int | None
    direction: str
    characteristic_uuid: str | None
    raw: bytes
    opcode: int | None
    frame_kind: str
    checksum_valid: bool | None
    decoder_id: str
    decoder_version: int
    decoded_fields: dict[str, Any]
    decode_error: str | None
    measurement: StoredMeasurement | None

    @property
    def raw_hex(self) -> str:
        return self.raw.hex()


@dataclass(frozen=True, slots=True)
class MeasurementSessionSummary:
    """Session metadata and aggregate evidence counts without frame bodies.

    This is the read-optimized record used by history listings and session
    metadata reads.  The canonical frame stream remains available through
    :meth:`SQLiteMeasurementStore.get_session`, but callers that only need a
    summary never materialize it.
    """

    id: str
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None
    display_timezone: str
    device_alias: str | None
    model_label: str | None
    address_hash: str | None
    requested_unit: str | None
    condition: str | None
    capture_id: str | None
    metadata: dict[str, Any]
    quality: MeasurementQuality
    quality_version: int
    quality_reason: str | None
    completion_reason: str | None
    selected_frame_sequence: int | None
    selection_policy_version: int | None
    frame_count: int
    measurement_frame_count: int
    decoder_versions: tuple[int, ...]

    @property
    def decoder_version(self) -> int | None:
        """Return one decoder version only when the session is uniform."""

        return self.decoder_versions[0] if len(self.decoder_versions) == 1 else None

    @property
    def started_at_local(self) -> datetime:
        return self.started_at.astimezone(ZoneInfo(self.display_timezone))

    @property
    def ended_at_local(self) -> datetime | None:
        if self.ended_at is None:
            return None
        return self.ended_at.astimezone(ZoneInfo(self.display_timezone))


@dataclass(frozen=True, slots=True)
class MeasurementSession:
    """A complete or in-progress weigh-in session.

    ``selected_frame_sequence`` is intentionally optional. A session can be
    complete while retaining every frame and making no unsupported claim about
    which frame is the product-level final sample.
    """

    id: str
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None
    display_timezone: str
    device_alias: str | None
    model_label: str | None
    address_hash: str | None
    requested_unit: str | None
    condition: str | None
    capture_id: str | None
    metadata: dict[str, Any]
    quality: MeasurementQuality
    quality_version: int = QUALITY_VERSION
    quality_reason: str | None = None
    completion_reason: str | None = None
    selected_frame_sequence: int | None = None
    selection_policy_version: int | None = None
    frames: tuple[StoredFrame, ...] = ()

    @property
    def started_at_local(self) -> datetime:
        return self.started_at.astimezone(ZoneInfo(self.display_timezone))

    @property
    def ended_at_local(self) -> datetime | None:
        if self.ended_at is None:
            return None
        return self.ended_at.astimezone(ZoneInfo(self.display_timezone))

    @property
    def measurements(self) -> tuple[StoredFrame, ...]:
        return tuple(frame for frame in self.frames if frame.measurement is not None)

    @property
    def selected_frame(self) -> StoredFrame | None:
        if self.selected_frame_sequence is None:
            return None
        return next(
            frame for frame in self.frames if frame.sequence == self.selected_frame_sequence
        )


__all__ = [
    "AcquisitionOperation",
    "DeviceConnection",
    "KnownDevice",
    "MeasurementSession",
    "MeasurementSessionSummary",
    "OperationStatus",
    "SessionStatus",
    "StoredFrame",
    "StoredMeasurement",
]
