"""Structured, agent-safe MCP views over Tracky's canonical records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from tracky_mcp.protocol import BurstAssembler, MeasurementFrame, decode_frame
from tracky_mcp.storage import (
    AcquisitionOperation,
    KnownDevice,
    MeasurementSession,
    MeasurementSessionSummary,
    StoredFrame,
)

CONTRACT_VERSION = 1
TRANSPORT_VERSION = 1
SELECTION_POLICY_VERSION = 1


class DeviceView(BaseModel):
    id: str = Field(description="Opaque local device ID; never a BLE address")
    advertised_name: str | None
    alias: str | None
    model_label: str | None
    address_hash: str = Field(description="Non-connecting, truncated address hash")
    first_seen_at: datetime
    last_seen_at: datetime
    advertised_service_uuids: list[str]
    metadata: dict[str, Any]
    resource_uri: str

    @classmethod
    def from_record(cls, device: KnownDevice) -> DeviceView:
        return cls(
            id=device.id,
            advertised_name=device.advertised_name,
            alias=device.alias,
            model_label=device.model_label,
            address_hash=device.address_hash,
            first_seen_at=device.first_seen_at,
            last_seen_at=device.last_seen_at,
            advertised_service_uuids=list(device.advertised_service_uuids),
            metadata=device.metadata,
            resource_uri=f"tracky://devices/{device.id}",
        )


class DeviceList(BaseModel):
    devices: list[DeviceView]


class OperationView(BaseModel):
    id: str
    kind: str
    status: Literal["pending", "running", "complete", "failed", "cancelled"]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    session_id: str | None
    error_code: str | None
    error_message: str | None
    metadata: dict[str, Any]
    resource_uri: str
    session_resource_uri: str | None

    @classmethod
    def from_record(cls, operation: AcquisitionOperation) -> OperationView:
        session_uri = (
            None
            if operation.session_id is None
            else f"tracky://sessions/{operation.session_id}"
        )
        return cls(
            id=operation.id,
            kind=operation.kind,
            status=operation.status.value,
            created_at=operation.created_at,
            started_at=operation.started_at,
            finished_at=operation.finished_at,
            session_id=operation.session_id,
            error_code=operation.error_code,
            error_message=operation.error_message,
            metadata=operation.metadata,
            resource_uri=f"tracky://operations/{operation.id}",
            session_resource_uri=session_uri,
        )


class ContractVersions(BaseModel):
    """Version identifiers that qualify one observation projection."""

    transport_version: int = TRANSPORT_VERSION
    decoder_version: int | None
    decoder_versions: list[int]
    selection_policy_version: int = SELECTION_POLICY_VERSION
    quality_version: int


class ErrorDetail(BaseModel):
    """Stable, machine-readable outcome detail for a read failure."""

    code: Literal["no_sessions", "session_not_found", "invalid_cursor"]
    message: str
    session_id: str | None = None


class WeightEvidence(BaseModel):
    """Source weight fields without consumer-side conversion."""

    raw: int
    divisor: int
    unit: str
    provenance: str


class FrameReference(BaseModel):
    """A stable reference to one frame in the canonical evidence resource."""

    session_id: str
    sequence: int
    resource_uri: str


class RawFramesReference(BaseModel):
    """O(1) metadata reference to a session's ordered frame resource."""

    resource_uri: str
    count: int


class SelectedEvidence(BaseModel):
    """Optional source-weight selection explicitly recorded by Linux."""

    frame_sequence: int
    weight: WeightEvidence | None


class MeasurementView(BaseModel):
    protocol_type: int
    weight_raw_u16_be: int
    weight_scale_divisor: int
    weight_unit: str
    weight_kg: str = Field(description="Exact decimal derived from raw/divisor")
    weight_formula: str
    weight_provenance: str
    weight: WeightEvidence
    b5: int
    b6: int
    opaque_words: list[int]
    word_layout: str | None
    word_provenance: str
    opaque_unit_evidence: str | None


_LEGACY_FIELD_RENAMES = {
    "resistance_raw": "opaque_words",
    "resistance_layout": "word_layout",
    "resistance_unit": "opaque_unit_evidence",
    "resistance_provenance": "word_provenance",
}
_FORBIDDEN_LEGACY_FIELD_PARTS = ("resistance", "impedance", "ohm")


def _consumer_decoded_fields(frame: StoredFrame) -> dict[str, Any]:
    """Project legacy decoded fields without exporting semantic labels.

    Storage keeps the original JSON unchanged for forensic compatibility. The
    MCP projection may rename known legacy keys to opaque evidence names and
    omits unknown electrical labels rather than presenting them as facts.
    """

    projected: dict[str, Any] = {}
    for key, value in frame.decoded_fields.items():
        normalized = key.casefold()
        renamed = _LEGACY_FIELD_RENAMES.get(normalized)
        if renamed is not None:
            projected.setdefault(renamed, value)
            continue
        if any(part in normalized for part in _FORBIDDEN_LEGACY_FIELD_PARTS):
            continue
        projected[key] = value
    return projected


class FrameView(BaseModel):
    sequence: int
    observed_at: datetime | None
    elapsed_ms: int | None
    direction: Literal["rx", "tx"]
    characteristic_uuid: str | None
    raw_hex: str
    opcode: int | None
    frame_kind: str
    checksum_valid: bool | None
    decoder_id: str
    decoder_version: int
    decoded_fields: dict[str, Any]
    decode_error: str | None
    measurement: MeasurementView | None

    @classmethod
    def from_record(cls, frame: StoredFrame) -> FrameView:
        measurement = frame.measurement
        measurement_view = None
        if measurement is not None:
            words = list(measurement.word_block)
            measurement_view = MeasurementView(
                protocol_type=measurement.protocol_type,
                weight_raw_u16_be=measurement.weight_raw_u16_be,
                weight_scale_divisor=measurement.weight_scale_divisor,
                weight_unit=measurement.weight_unit,
                weight_kg=format(measurement.weight_kg, "f"),
                weight_formula=measurement.weight_formula,
                weight_provenance=measurement.weight_provenance,
                weight=WeightEvidence(
                    raw=measurement.weight_raw_u16_be,
                    divisor=measurement.weight_scale_divisor,
                    unit=measurement.weight_unit,
                    provenance=measurement.weight_provenance,
                ),
                b5=measurement.b5,
                b6=measurement.b6,
                opaque_words=words,
                word_layout=measurement.word_layout,
                word_provenance=measurement.word_provenance,
                opaque_unit_evidence=measurement.opaque_unit_evidence,
            )
        return cls(
            sequence=frame.sequence,
            observed_at=frame.observed_at,
            elapsed_ms=frame.elapsed_ms,
            direction=frame.direction,
            characteristic_uuid=frame.characteristic_uuid,
            raw_hex=frame.raw_hex,
            opcode=frame.opcode,
            frame_kind=frame.frame_kind,
            checksum_valid=frame.checksum_valid,
            decoder_id=frame.decoder_id,
            decoder_version=frame.decoder_version,
            decoded_fields=_consumer_decoded_fields(frame),
            decode_error=frame.decode_error,
            measurement=measurement_view,
        )


SessionRecord = MeasurementSession | MeasurementSessionSummary


def _frame_count(session: SessionRecord) -> int:
    count = getattr(session, "frame_count", None)
    return len(session.frames) if count is None else count


def _measurement_frame_count(session: SessionRecord) -> int:
    count = getattr(session, "measurement_frame_count", None)
    return len(session.measurements) if count is None else count


def _decoder_versions(session: SessionRecord) -> tuple[int, ...]:
    stored = getattr(session, "decoder_versions", None)
    if stored is not None:
        return tuple(stored)
    return tuple(sorted({frame.decoder_version for frame in session.frames}))


def _frame_references(session_id: str, count: int) -> list[FrameReference]:
    resource_uri = f"tracky://sessions/{session_id}/frames"
    return [
        FrameReference(session_id=session_id, sequence=sequence, resource_uri=resource_uri)
        for sequence in range(count)
    ]


def _opaque_blocks(session: MeasurementSession) -> tuple[list[int] | None, list[int] | None]:
    """Return only the latest pair assembled by the wire-valid burst rules."""

    assembler = BurstAssembler()
    for stored_frame in session.frames:
        if stored_frame.direction != "rx":
            continue
        try:
            decoded = decode_frame(stored_frame.raw)
        except ValueError:
            assembler.interrupt()
            continue
        if isinstance(decoded, MeasurementFrame):
            assembler.add(decoded)
        else:
            assembler.interrupt()

    if not assembler.completed:
        return None, None
    burst = assembler.completed[-1]
    return list(burst.block_a), list(burst.block_b)


def _selected_evidence(session: SessionRecord) -> SelectedEvidence | None:
    if isinstance(session, MeasurementSessionSummary):
        if session.selected_frame_sequence is None:
            return None
        return SelectedEvidence(
            frame_sequence=session.selected_frame_sequence,
            weight=None,
        )
    frame = session.selected_frame
    if frame is None:
        return None
    measurement = frame.measurement
    if measurement is None:
        return SelectedEvidence(
            frame_sequence=frame.sequence,
            weight=None,
        )
    return SelectedEvidence(
        frame_sequence=frame.sequence,
        weight=WeightEvidence(
            raw=measurement.weight_raw_u16_be,
            divisor=measurement.weight_scale_divisor,
            unit=measurement.weight_unit,
            provenance=measurement.weight_provenance,
        ),
    )


class SessionSummary(BaseModel):
    contract_version: int = CONTRACT_VERSION
    id: str
    session_id: str
    status: Literal["open", "complete", "aborted"]
    started_at: datetime
    ended_at: datetime | None
    display_timezone: str
    started_at_display: datetime
    ended_at_display: datetime | None
    device_alias: str | None
    model_label: str | None
    address_hash: str | None
    requested_unit: str | None
    condition: str | None
    capture_id: str | None
    quality: Literal["accepted", "contact_failed", "indeterminate"]
    quality_version: int
    quality_reason: str | None
    completion_reason: str | None
    selected_frame_sequence: int | None = Field(
        description="Null unless a separately justified final-sample policy selected a frame"
    )
    frame_count: int
    measurement_frame_count: int
    raw_frames: RawFramesReference
    versions: ContractVersions
    resource_uri: str
    frames_resource_uri: str

    @classmethod
    def from_record(cls, session: SessionRecord) -> SessionSummary:
        decoder_versions = list(_decoder_versions(session))
        versions = ContractVersions(
            decoder_version=(decoder_versions[0] if len(decoder_versions) == 1 else None),
            decoder_versions=decoder_versions,
            quality_version=session.quality_version,
        )
        return cls(
            id=session.id,
            session_id=session.id,
            status=session.status.value,
            started_at=session.started_at,
            ended_at=session.ended_at,
            display_timezone=session.display_timezone,
            started_at_display=session.started_at_local,
            ended_at_display=session.ended_at_local,
            device_alias=session.device_alias,
            model_label=session.model_label,
            address_hash=session.address_hash,
            requested_unit=session.requested_unit,
            condition=session.condition,
            capture_id=session.capture_id,
            quality=session.quality.value,
            quality_version=session.quality_version,
            quality_reason=session.quality_reason,
            completion_reason=session.completion_reason,
            selected_frame_sequence=session.selected_frame_sequence,
            frame_count=_frame_count(session),
            measurement_frame_count=_measurement_frame_count(session),
            raw_frames=RawFramesReference(
                resource_uri=f"tracky://sessions/{session.id}/frames",
                count=_frame_count(session),
            ),
            versions=versions,
            resource_uri=f"tracky://sessions/{session.id}",
            frames_resource_uri=f"tracky://sessions/{session.id}/frames",
        )


class SessionList(BaseModel):
    ok: bool = True
    contract_version: int = CONTRACT_VERSION
    sessions: list[SessionSummary] = Field(default_factory=list)
    next_cursor: str | None = None
    error: ErrorDetail | None = None


class SessionResource(BaseModel):
    ok: bool = True
    contract_version: int = CONTRACT_VERSION
    session_id: str | None = None
    summary: SessionSummary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_frames: RawFramesReference | None = None
    selected: SelectedEvidence | None = None
    versions: ContractVersions | None = None
    quality: Literal["accepted", "contact_failed", "indeterminate"] | None = None
    quality_version: int | None = None
    opaque_block_a: list[int] | None = None
    opaque_block_b: list[int] | None = None
    error: ErrorDetail | None = None

    @classmethod
    def from_record(cls, session: SessionRecord) -> SessionResource:
        summary = SessionSummary.from_record(session)
        if isinstance(session, MeasurementSession):
            block_a, block_b = _opaque_blocks(session)
        else:
            block_a = block_b = None
        selected = _selected_evidence(session)
        return cls(
            session_id=session.id,
            summary=summary,
            metadata=session.metadata,
            raw_frames=RawFramesReference(
                resource_uri=f"tracky://sessions/{session.id}/frames",
                count=summary.frame_count,
            ),
            selected=selected,
            versions=summary.versions,
            quality=summary.quality,
            quality_version=summary.quality_version,
            opaque_block_a=block_a,
            opaque_block_b=block_b,
        )


class FramesResource(BaseModel):
    ok: bool = True
    contract_version: int = CONTRACT_VERSION
    session_id: str | None = None
    selected_frame_sequence: int | None = None
    raw_frames: list[FrameReference] = Field(default_factory=list)
    selected: SelectedEvidence | None = None
    versions: ContractVersions | None = None
    quality: Literal["accepted", "contact_failed", "indeterminate"] | None = None
    quality_version: int | None = None
    opaque_block_a: list[int] | None = None
    opaque_block_b: list[int] | None = None
    interpretation_warning: str = (
        "Frames are an ordered wire-evidence stream; word blocks remain opaque and "
        "quality is separate from checksum validity."
    )
    frames: list[FrameView] = Field(default_factory=list)
    error: ErrorDetail | None = None

    @classmethod
    def from_record(cls, session: MeasurementSession) -> FramesResource:
        summary = SessionSummary.from_record(session)
        block_a, block_b = _opaque_blocks(session)
        return cls(
            session_id=session.id,
            selected_frame_sequence=session.selected_frame_sequence,
            raw_frames=_frame_references(session.id, len(session.frames)),
            selected=_selected_evidence(session),
            versions=summary.versions,
            quality=summary.quality,
            quality_version=summary.quality_version,
            opaque_block_a=block_a,
            opaque_block_b=block_b,
            frames=[FrameView.from_record(frame) for frame in session.frames],
        )


__all__ = [
    "CONTRACT_VERSION",
    "ContractVersions",
    "DeviceList",
    "ErrorDetail",
    "DeviceView",
    "FrameReference",
    "FrameView",
    "FramesResource",
    "MeasurementView",
    "OperationView",
    "RawFramesReference",
    "SelectedEvidence",
    "SessionList",
    "SessionResource",
    "SessionSummary",
    "WeightEvidence",
]
