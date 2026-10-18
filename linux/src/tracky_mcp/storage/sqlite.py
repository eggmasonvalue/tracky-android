"""SQLite system of record for local, single-user measurement sessions."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tracky_mcp.protocol import (
    DECODER_ID,
    DECODER_VERSION,
    QUALITY_VERSION,
    WEIGHT_SELECTION_POLICY_VERSION,
    CommandFrame,
    DecodedFrame,
    FrameDecodeError,
    InfoFrame,
    MeasurementFrame,
    MeasurementQuality,
    StatusFrame,
    UnknownFrame,
    decode_frame,
)

from .models import (
    AcquisitionOperation,
    DeviceConnection,
    KnownDevice,
    MeasurementSession,
    MeasurementSessionSummary,
    OperationStatus,
    SessionStatus,
    StoredFrame,
    StoredMeasurement,
)

SCHEMA_REVISION = 5
DEFAULT_DISPLAY_TIMEZONE = "Asia/Kolkata"
DEFAULT_DB_FILENAME = "tracky.sqlite3"

_SESSION_SUMMARY_QUERY = """
SELECT
    s.*,
    (
        SELECT COUNT(*)
        FROM frames AS f
        WHERE f.session_id = s.id
    ) AS frame_count,
    (
        SELECT COUNT(*)
        FROM measurement_frames AS m
        WHERE m.session_id = s.id
    ) AS measurement_frame_count,
    (
        SELECT GROUP_CONCAT(DISTINCT f.decoder_version)
        FROM frames AS f
        WHERE f.session_id = s.id
    ) AS decoder_versions
FROM measurement_sessions AS s
"""

_SCHEMA = """
CREATE TABLE known_devices (
    id TEXT PRIMARY KEY,
    connection_target TEXT NOT NULL,
    connection_key TEXT NOT NULL UNIQUE,
    address_hash TEXT NOT NULL,
    advertised_name TEXT,
    alias TEXT,
    model_label TEXT,
    first_seen_at_utc TEXT NOT NULL,
    last_seen_at_utc TEXT NOT NULL,
    advertised_service_uuids_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK (last_seen_at_utc >= first_seen_at_utc)
) STRICT;

CREATE TABLE measurement_sessions (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('open', 'complete', 'aborted')),
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    display_timezone TEXT NOT NULL,
    device_alias TEXT,
    model_label TEXT,
    address_hash TEXT,
    requested_unit TEXT,
    condition TEXT,
    capture_id TEXT UNIQUE,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    quality TEXT NOT NULL DEFAULT 'indeterminate' CHECK (
        quality IN ('accepted', 'contact_failed', 'indeterminate')
    ),
    quality_version INTEGER NOT NULL DEFAULT 1 CHECK (quality_version >= 1),
    quality_reason TEXT,
    completion_reason TEXT,
    selected_frame_sequence INTEGER,
    selection_policy_version INTEGER CHECK (
        selection_policy_version IS NULL OR selection_policy_version >= 1
    ),
    CHECK (ended_at_utc IS NULL OR ended_at_utc >= started_at_utc),
    FOREIGN KEY (id, selected_frame_sequence)
        REFERENCES frames(session_id, sequence)
) STRICT;

CREATE TABLE acquisition_operations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'complete', 'failed', 'cancelled')
    ),
    created_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    finished_at_utc TEXT,
    session_id TEXT REFERENCES measurement_sessions(id) ON DELETE RESTRICT,
    error_code TEXT,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK (started_at_utc IS NULL OR started_at_utc >= created_at_utc),
    CHECK (finished_at_utc IS NULL OR finished_at_utc >= created_at_utc),
    CHECK (
        (status IN ('pending', 'running') AND finished_at_utc IS NULL)
        OR (status IN ('complete', 'failed', 'cancelled') AND finished_at_utc IS NOT NULL)
    ),
    CHECK (
        (status IN ('failed', 'cancelled'))
        OR (error_code IS NULL AND error_message IS NULL)
    )
) STRICT;

CREATE TABLE frames (
    session_id TEXT NOT NULL REFERENCES measurement_sessions(id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    observed_at_utc TEXT,
    elapsed_ms INTEGER CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
    direction TEXT NOT NULL CHECK (direction IN ('rx', 'tx')),
    characteristic_uuid TEXT,
    raw BLOB NOT NULL,
    opcode INTEGER CHECK (opcode IS NULL OR opcode BETWEEN 0 AND 255),
    frame_kind TEXT NOT NULL,
    checksum_valid INTEGER CHECK (checksum_valid IS NULL OR checksum_valid IN (0, 1)),
    decoder_id TEXT NOT NULL,
    decoder_version INTEGER NOT NULL CHECK (decoder_version >= 1),
    decoded_fields_json TEXT NOT NULL DEFAULT '{}',
    decode_error TEXT,
    PRIMARY KEY (session_id, sequence)
) STRICT;

CREATE TABLE measurement_frames (
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    protocol_type INTEGER NOT NULL CHECK (protocol_type BETWEEN 0 AND 255),
    weight_raw_u16_be INTEGER NOT NULL CHECK (weight_raw_u16_be BETWEEN 0 AND 65535),
    weight_scale_divisor INTEGER NOT NULL CHECK (weight_scale_divisor > 0),
    weight_unit TEXT NOT NULL,
    weight_formula TEXT NOT NULL,
    weight_provenance TEXT NOT NULL,
    b5 INTEGER NOT NULL CHECK (b5 BETWEEN 0 AND 255),
    b6 INTEGER NOT NULL CHECK (b6 BETWEEN 0 AND 255),
    word_layout TEXT,
    word_provenance TEXT NOT NULL,
    opaque_unit_evidence TEXT,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY (session_id, sequence)
        REFERENCES frames(session_id, sequence) ON DELETE RESTRICT
) STRICT;

CREATE TABLE word_values (
    session_id TEXT NOT NULL,
    frame_sequence INTEGER NOT NULL,
    value_index INTEGER NOT NULL CHECK (value_index >= 0),
    raw_value INTEGER NOT NULL CHECK (raw_value BETWEEN 0 AND 65535),
    PRIMARY KEY (session_id, frame_sequence, value_index),
    FOREIGN KEY (session_id, frame_sequence)
        REFERENCES measurement_frames(session_id, sequence) ON DELETE RESTRICT
) STRICT;

CREATE INDEX devices_last_seen_idx ON known_devices(last_seen_at_utc DESC);
CREATE INDEX frames_opcode_idx ON frames(opcode);
CREATE INDEX sessions_started_at_idx ON measurement_sessions(started_at_utc DESC);
CREATE INDEX operations_created_at_idx ON acquisition_operations(created_at_utc DESC);
CREATE INDEX operations_status_idx ON acquisition_operations(status);
CREATE INDEX measurement_weight_raw_idx
    ON measurement_frames(weight_raw_u16_be, weight_scale_divisor);
"""


class StorageError(RuntimeError):
    """Base class for local storage failures with a stable public meaning."""


class SchemaRevisionError(StorageError):
    """Raised instead of silently opening an unknown database layout."""


class SessionNotFoundError(StorageError):
    """Raised when an operation targets a nonexistent session."""


class SessionClosedError(StorageError):
    """Raised when frames are appended to a completed or aborted session."""


class OperationNotFoundError(StorageError):
    """Raised when an operation handle does not exist."""


class OperationClosedError(StorageError):
    """Raised when a terminal operation receives another transition."""


class DeviceNotFoundError(StorageError):
    """Raised when an opaque local device ID is unknown."""


def default_database_path(*, environ: Mapping[str, str] | None = None) -> Path:
    """Return the Linux XDG path for Tracky's local database."""

    values = os.environ if environ is None else environ
    data_home = values.get("XDG_DATA_HOME")
    if data_home:
        root = Path(data_home).expanduser()
    else:
        home = values.get("HOME")
        if not home:
            raise RuntimeError("HOME or XDG_DATA_HOME is required for the default database path")
        root = Path(home).expanduser() / ".local" / "share"
    return root / "tracky-mcp" / DEFAULT_DB_FILENAME


def _aware(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value


def _timestamp(value: datetime, *, name: str) -> str:
    utc = _aware(value, name=name).astimezone(timezone.utc)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA display timezone: {name}") from exc
    return name


def _json_object(value: Mapping[str, Any] | None, *, name: str) -> str:
    try:
        return json.dumps(dict(value or {}), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain JSON-serializable values") from exc


def _connection_identity(target: str) -> tuple[str, str]:
    value = target.strip()
    if not value:
        raise ValueError("connection target must not be empty")
    compact = value.replace(":", "").replace("-", "")
    if len(compact) == 12 and all(character in "0123456789abcdefABCDEF" for character in compact):
        key = compact.upper()
    else:
        key = value.casefold()
    address_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return key, address_hash


def _service_uuids_json(values: Iterable[str]) -> str:
    normalized = sorted({str(value).strip().lower() for value in values if str(value).strip()})
    return json.dumps(normalized, separators=(",", ":"))


def _decoded_fields(frame: DecodedFrame) -> dict[str, Any]:
    fields: dict[str, Any] = {"opcode_name": frame.opcode_name}
    if isinstance(frame, MeasurementFrame):
        fields.update(
            {
                "protocol_type": frame.protocol_type,
                "weight_raw_u16_be": frame.weight_raw_u16_be,
                "weight_scale_divisor": frame.weight_scale_divisor,
                "weight_unit": frame.weight_unit,
                "b5": frame.b5,
                "b6": frame.b6,
                "opaque_words": list(frame.word_block),
                "opaque_unit_evidence": frame.opaque_unit_evidence,
            }
        )
    elif isinstance(frame, InfoFrame):
        fields.update(
            {
                "protocol_type": frame.protocol_type,
                "length_field": frame.length_field,
                "info_payload_hex": frame.info_payload.hex(),
            }
        )
    elif isinstance(frame, StatusFrame):
        fields.update(
            {
                "protocol_type": frame.protocol_type,
                "status_byte": frame.status_byte,
                "length_field": frame.length_field,
                "status_payload_hex": frame.status_payload.hex(),
            }
        )
    elif isinstance(frame, CommandFrame):
        fields.update(
            {
                "command_name": frame.command_name,
                "command_payload_hex": frame.command_payload.hex(),
                "protocol_type": frame.protocol_type,
                "unit_byte": frame.unit_byte,
                "qn_epoch_seconds": frame.qn_epoch_seconds,
            }
        )
    return fields


def _frame_kind(frame: DecodedFrame) -> str:
    if isinstance(frame, MeasurementFrame):
        return "measurement"
    if isinstance(frame, InfoFrame):
        return "info"
    if isinstance(frame, StatusFrame):
        return "status"
    if isinstance(frame, CommandFrame):
        return "command"
    if isinstance(frame, UnknownFrame):
        return "unknown"
    return type(frame).__name__


def _quality_value(value: MeasurementQuality | str) -> str:
    return MeasurementQuality(value).value


def _decoder_versions(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(sorted({int(part) for part in value.split(",")}))


class SQLiteMeasurementStore:
    """Persist complete sessions while retaining every raw frame losslessly.

    Revision 3 databases migrate transactionally to the current layout while
    preserving evidence. An unknown revision fails loudly so an experimental
    database is never reinterpreted under the wrong layout.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        read_only: bool = False,
    ) -> None:
        selected = default_database_path() if path is None else Path(path)
        self.path = selected
        self.read_only = read_only
        self._memory = str(selected) == ":memory:"
        if self.read_only and self._memory:
            raise ValueError("an in-memory database cannot be opened read-only")
        if not self.read_only and not self._memory:
            selected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.read_only:
            if not selected.is_file():
                raise StorageError(f"read-only database does not exist: {selected}")
            self._connection = sqlite3.connect(
                f"{selected.resolve().as_uri()}?mode=ro",
                uri=True,
            )
        else:
            self._connection = sqlite3.connect(str(selected))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if self.read_only:
            self._connection.execute("PRAGMA query_only = ON")
        self._initialize()
        if not self.read_only and not self._memory:
            try:
                selected.chmod(0o600)
            except OSError:
                pass

    def _initialize(self) -> None:
        revision = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if revision == 0:
            if self.read_only:
                raise SchemaRevisionError("read-only database has no initialized schema")
            with self._connection:
                self._connection.executescript(_SCHEMA)
                self._connection.execute(f"PRAGMA user_version = {SCHEMA_REVISION}")
            if not self._memory:
                self._connection.execute("PRAGMA journal_mode = WAL")
            return
        if revision == 3:
            if self.read_only:
                raise SchemaRevisionError(
                    "read-only database is revision 3; migrate it with the acquisition store"
                )
            self._migrate_revision_3_to_4()
            revision = 4
        if revision == 4:
            if self.read_only:
                raise SchemaRevisionError(
                    "read-only database is revision 4; migrate it with the acquisition store"
                )
            self._migrate_revision_4_to_5()
            revision = 5
        if revision != SCHEMA_REVISION:
            raise SchemaRevisionError(
                f"database schema revision {revision} is unsupported; expected {SCHEMA_REVISION}"
            )

    def _migrate_revision_3_to_4(self) -> None:
        """Upgrade the shipped revision-3 layout without rewriting evidence.

        SQLite's transactional column/table renames retain every row, raw blob,
        timestamp, checksum value, decoded JSON field, and foreign-key link.
        The former unit column is retained under an explicitly opaque name
        rather than being discarded or reinterpreted.
        """

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                ALTER TABLE measurement_sessions
                ADD COLUMN quality TEXT NOT NULL DEFAULT 'indeterminate'
                CHECK (quality IN ('accepted', 'contact_failed', 'indeterminate'))
                """
            )
            self._connection.execute(
                """
                ALTER TABLE measurement_sessions
                ADD COLUMN quality_version INTEGER NOT NULL DEFAULT 1
                CHECK (quality_version >= 1)
                """
            )
            self._connection.execute(
                "ALTER TABLE measurement_sessions ADD COLUMN quality_reason TEXT"
            )
            self._connection.execute(
                "ALTER TABLE measurement_sessions ADD COLUMN completion_reason TEXT"
            )
            self._connection.execute(
                "ALTER TABLE measurement_frames RENAME COLUMN resistance_layout TO word_layout"
            )
            self._connection.execute(
                "ALTER TABLE measurement_frames RENAME COLUMN resistance_provenance "
                "TO word_provenance"
            )
            self._connection.execute(
                "ALTER TABLE measurement_frames RENAME COLUMN resistance_unit "
                "TO opaque_unit_evidence"
            )
            self._connection.execute("ALTER TABLE resistance_values RENAME TO word_values")
            self._connection.execute("PRAGMA user_version = 4")
            self._connection.commit()
        except sqlite3.DatabaseError as exc:
            self._connection.rollback()
            raise SchemaRevisionError("database schema revision 3 migration failed") from exc

    def _migrate_revision_4_to_5(self) -> None:
        """Add explicit provenance for the Linux weight-selection policy."""

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                ALTER TABLE measurement_sessions
                ADD COLUMN selection_policy_version INTEGER
                CHECK (selection_policy_version IS NULL OR selection_policy_version >= 1)
                """
            )
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_REVISION}")
            self._connection.commit()
        except sqlite3.DatabaseError as exc:
            self._connection.rollback()
            raise SchemaRevisionError("database schema revision 4 migration failed") from exc

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteMeasurementStore:
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    def register_device(
        self,
        connection_target: str,
        *,
        seen_at: datetime,
        advertised_name: str | None = None,
        advertised_service_uuids: Iterable[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> KnownDevice:
        """Upsert one private BLE target and return its stable opaque identity."""

        target = connection_target.strip()
        connection_key, address_hash = _connection_identity(target)
        seen_text = _timestamp(seen_at, name="seen_at")
        identifier = str(uuid4())
        services = {str(value) for value in advertised_service_uuids}
        merged_metadata = dict(metadata or {})
        with self._connection:
            existing = self._connection.execute(
                """
                SELECT advertised_service_uuids_json, metadata_json
                FROM known_devices WHERE connection_key = ?
                """,
                (connection_key,),
            ).fetchone()
            if existing is not None:
                services.update(json.loads(existing["advertised_service_uuids_json"]))
                merged_metadata = {
                    **json.loads(existing["metadata_json"]),
                    **merged_metadata,
                }
            self._connection.execute(
                """
                INSERT INTO known_devices (
                    id, connection_target, connection_key, address_hash,
                    advertised_name, first_seen_at_utc, last_seen_at_utc,
                    advertised_service_uuids_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_key) DO UPDATE SET
                    connection_target = excluded.connection_target,
                    advertised_name = COALESCE(
                        excluded.advertised_name, known_devices.advertised_name
                    ),
                    last_seen_at_utc = MAX(
                        excluded.last_seen_at_utc, known_devices.last_seen_at_utc
                    ),
                    advertised_service_uuids_json = excluded.advertised_service_uuids_json,
                    metadata_json = excluded.metadata_json
                """,
                (
                    identifier,
                    target,
                    connection_key,
                    address_hash,
                    advertised_name,
                    seen_text,
                    seen_text,
                    _service_uuids_json(services),
                    _json_object(merged_metadata, name="device metadata"),
                ),
            )
            row = self._connection.execute(
                "SELECT id FROM known_devices WHERE connection_key = ?", (connection_key,)
            ).fetchone()
        assert row is not None
        return self.get_device(row["id"])

    def configure_device(
        self,
        device_id: str,
        *,
        alias: str | None = None,
        model_label: str | None = None,
    ) -> KnownDevice:
        """Set user/local labels without exposing the private connection target."""

        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE known_devices SET alias = ?, model_label = ? WHERE id = ?
                """,
                (alias, model_label, device_id),
            )
            if cursor.rowcount == 0:
                raise DeviceNotFoundError(device_id)
        return self.get_device(device_id)

    def get_device(self, device_id: str) -> KnownDevice:
        row = self._connection.execute(
            "SELECT * FROM known_devices WHERE id = ?", (device_id,)
        ).fetchone()
        if row is None:
            raise DeviceNotFoundError(device_id)
        return self._known_device(row)

    def resolve_device(self, device_id: str) -> DeviceConnection:
        """Resolve an opaque ID to a private target only at the transport boundary."""

        row = self._connection.execute(
            "SELECT * FROM known_devices WHERE id = ?", (device_id,)
        ).fetchone()
        if row is None:
            raise DeviceNotFoundError(device_id)
        return DeviceConnection(device=self._known_device(row), target=row["connection_target"])

    def list_devices(self, *, limit: int = 100) -> list[KnownDevice]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        rows = self._connection.execute(
            """
            SELECT * FROM known_devices
            ORDER BY last_seen_at_utc DESC, id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._known_device(row) for row in rows]

    @staticmethod
    def _known_device(row: sqlite3.Row) -> KnownDevice:
        first_seen = _parse_timestamp(row["first_seen_at_utc"])
        last_seen = _parse_timestamp(row["last_seen_at_utc"])
        assert first_seen is not None and last_seen is not None
        return KnownDevice(
            id=row["id"],
            advertised_name=row["advertised_name"],
            alias=row["alias"],
            model_label=row["model_label"],
            address_hash=row["address_hash"],
            first_seen_at=first_seen,
            last_seen_at=last_seen,
            advertised_service_uuids=tuple(
                json.loads(row["advertised_service_uuids_json"])
            ),
            metadata=json.loads(row["metadata_json"]),
        )

    def create_operation(
        self,
        *,
        created_at: datetime,
        operation_id: str | None = None,
        kind: str = "weigh_in",
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """Create a pending operation and return its opaque handle."""

        identifier = operation_id or str(uuid4())
        if not identifier:
            raise ValueError("operation_id must not be empty")
        if not kind:
            raise ValueError("operation kind must not be empty")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO acquisition_operations (
                    id, kind, status, created_at_utc, metadata_json
                ) VALUES (?, ?, 'pending', ?, ?)
                """,
                (
                    identifier,
                    kind,
                    _timestamp(created_at, name="created_at"),
                    _json_object(metadata, name="metadata"),
                ),
            )
        return identifier

    def start_operation(
        self,
        operation_id: str,
        *,
        session_id: str,
        started_at: datetime,
    ) -> None:
        """Bind a pending operation to its durable session and mark it running."""

        started_text = _timestamp(started_at, name="started_at")
        with self._connection:
            session = self._connection.execute(
                "SELECT status FROM measurement_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session is None:
                raise SessionNotFoundError(session_id)
            if session["status"] != SessionStatus.OPEN.value:
                raise SessionClosedError(f"session {session_id} is {session['status']}")
            cursor = self._connection.execute(
                """
                UPDATE acquisition_operations
                SET status = 'running', started_at_utc = ?, session_id = ?
                WHERE id = ? AND status = 'pending'
                """,
                (started_text, session_id, operation_id),
            )
            if cursor.rowcount == 0:
                self._raise_operation_transition_error(operation_id)

    def complete_operation(self, operation_id: str, *, finished_at: datetime) -> None:
        self._finish_operation(
            operation_id,
            status=OperationStatus.COMPLETE,
            finished_at=finished_at,
        )

    def fail_operation(
        self,
        operation_id: str,
        *,
        finished_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        self._finish_operation(
            operation_id,
            status=OperationStatus.FAILED,
            finished_at=finished_at,
            error_code=error_code,
            error_message=error_message,
        )

    def cancel_operation(
        self,
        operation_id: str,
        *,
        finished_at: datetime,
        error_message: str = "Operation cancelled",
    ) -> None:
        self._finish_operation(
            operation_id,
            status=OperationStatus.CANCELLED,
            finished_at=finished_at,
            error_code="cancelled",
            error_message=error_message,
        )

    def finish_acquisition(
        self,
        operation_id: str,
        *,
        session_id: str,
        status: OperationStatus,
        finished_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        quality: MeasurementQuality | str = MeasurementQuality.INDETERMINATE,
        quality_reason: str | None = None,
        completion_reason: str | None = None,
        selected_frame_sequence: int | None = None,
        selection_policy_version: int | None = None,
    ) -> None:
        """Atomically close an operation and persist quality and selection provenance."""

        if status not in {
            OperationStatus.COMPLETE,
            OperationStatus.FAILED,
            OperationStatus.CANCELLED,
        }:
            raise ValueError("acquisition finish status must be terminal")
        if status is OperationStatus.COMPLETE and (error_code or error_message):
            raise ValueError("a completed acquisition cannot carry an error")
        if status is not OperationStatus.COMPLETE and not error_code:
            raise ValueError("a failed or cancelled acquisition requires an error code")
        if status is not OperationStatus.COMPLETE:
            selected_frame_sequence = None
            selection_policy_version = None
        if selected_frame_sequence is None and selection_policy_version is not None:
            raise ValueError("selection policy version requires a selected frame")
        if selected_frame_sequence is not None and selection_policy_version is None:
            raise ValueError("a selected frame requires a selection policy version")
        if (
            selected_frame_sequence is not None
            and selection_policy_version != WEIGHT_SELECTION_POLICY_VERSION
        ):
            raise ValueError("unsupported weight selection policy version")
        finished_text = _timestamp(finished_at, name="finished_at")
        quality_text = _quality_value(quality)
        session_status = (
            SessionStatus.COMPLETE
            if status is OperationStatus.COMPLETE
            else SessionStatus.ABORTED
        )
        with self._connection:
            operation = self._connection.execute(
                """
                SELECT status, session_id FROM acquisition_operations WHERE id = ?
                """,
                (operation_id,),
            ).fetchone()
            if operation is None:
                raise OperationNotFoundError(operation_id)
            if operation["status"] != OperationStatus.RUNNING.value:
                raise OperationClosedError(
                    f"operation {operation_id} is {operation['status']}"
                )
            if operation["session_id"] != session_id:
                raise ValueError("operation is not linked to the supplied session")
            self._require_open(session_id)
            if selected_frame_sequence is not None:
                selected = self._connection.execute(
                    """
                    SELECT 1 FROM measurement_frames AS m
                    JOIN frames AS f
                      ON f.session_id = m.session_id AND f.sequence = m.sequence
                    WHERE m.session_id = ? AND m.sequence = ?
                      AND f.checksum_valid = 1
                    """,
                    (session_id, selected_frame_sequence),
                ).fetchone()
                if selected is None:
                    raise ValueError("selected frame must be a wire-valid measurement")
            self._connection.execute(
                """
                UPDATE measurement_sessions
                SET status = ?, ended_at_utc = ?, quality = ?, quality_version = ?,
                    quality_reason = ?, completion_reason = ?,
                    selected_frame_sequence = ?, selection_policy_version = ?
                WHERE id = ?
                """,
                (
                    session_status.value,
                    finished_text,
                    quality_text,
                    QUALITY_VERSION,
                    quality_reason,
                    completion_reason,
                    selected_frame_sequence,
                    selection_policy_version,
                    session_id,
                ),
            )
            self._connection.execute(
                """
                UPDATE acquisition_operations
                SET status = ?, finished_at_utc = ?, error_code = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    finished_text,
                    error_code,
                    error_message,
                    operation_id,
                ),
            )

    def _finish_operation(
        self,
        operation_id: str,
        *,
        status: OperationStatus,
        finished_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in {
            OperationStatus.COMPLETE,
            OperationStatus.FAILED,
            OperationStatus.CANCELLED,
        }:
            raise ValueError("finish status must be terminal")
        finished_text = _timestamp(finished_at, name="finished_at")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE acquisition_operations
                SET status = ?, finished_at_utc = ?, error_code = ?, error_message = ?
                WHERE id = ? AND status IN ('pending', 'running')
                """,
                (
                    status.value,
                    finished_text,
                    error_code,
                    error_message,
                    operation_id,
                ),
            )
            if cursor.rowcount == 0:
                self._raise_operation_transition_error(operation_id)

    def _raise_operation_transition_error(self, operation_id: str) -> None:
        row = self._connection.execute(
            "SELECT status FROM acquisition_operations WHERE id = ?", (operation_id,)
        ).fetchone()
        if row is None:
            raise OperationNotFoundError(operation_id)
        raise OperationClosedError(f"operation {operation_id} is {row['status']}")

    def get_operation(self, operation_id: str) -> AcquisitionOperation:
        row = self._connection.execute(
            "SELECT * FROM acquisition_operations WHERE id = ?", (operation_id,)
        ).fetchone()
        if row is None:
            raise OperationNotFoundError(operation_id)
        created_at = _parse_timestamp(row["created_at_utc"])
        assert created_at is not None
        return AcquisitionOperation(
            id=row["id"],
            kind=row["kind"],
            status=OperationStatus(row["status"]),
            created_at=created_at,
            started_at=_parse_timestamp(row["started_at_utc"]),
            finished_at=_parse_timestamp(row["finished_at_utc"]),
            session_id=row["session_id"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            metadata=json.loads(row["metadata_json"]),
        )

    def list_operations(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AcquisitionOperation]:
        """Return newest operations first without relying on connection state."""

        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        rows = self._connection.execute(
            """
            SELECT id FROM acquisition_operations
            ORDER BY created_at_utc DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [self.get_operation(row["id"]) for row in rows]

    def recover_interrupted_operations(self, *, recovered_at: datetime) -> list[str]:
        """Fail nonterminal handles and abort linked open sessions after restart."""

        recovered_text = _timestamp(recovered_at, name="recovered_at")
        with self._connection:
            rows = self._connection.execute(
                """
                SELECT id, session_id FROM acquisition_operations
                WHERE status IN ('pending', 'running')
                ORDER BY created_at_utc
                """
            ).fetchall()
            session_ids = [row["session_id"] for row in rows if row["session_id"] is not None]
            self._connection.executemany(
                """
                UPDATE measurement_sessions
                SET status = 'aborted', ended_at_utc = ?, quality = ?,
                    quality_version = ?, quality_reason = ?, completion_reason = ?
                WHERE id = ? AND status = 'open'
                """,
                (
                    (recovered_text, MeasurementQuality.INDETERMINATE.value, QUALITY_VERSION,
                     "process_restarted", "process_restarted", session_id)
                    for session_id in session_ids
                ),
            )
            self._connection.execute(
                """
                UPDATE acquisition_operations
                SET status = 'failed', finished_at_utc = ?,
                    error_code = 'process_restarted',
                    error_message = 'Acquisition interrupted by process restart'
                WHERE status IN ('pending', 'running')
                """,
                (recovered_text,),
            )
        return [row["id"] for row in rows]

    def create_session(
        self,
        *,
        started_at: datetime,
        session_id: str | None = None,
        display_timezone: str = DEFAULT_DISPLAY_TIMEZONE,
        device_alias: str | None = None,
        model_label: str | None = None,
        address_hash: str | None = None,
        requested_unit: str | None = None,
        condition: str | None = None,
        capture_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """Create an open session and return its opaque identifier."""

        identifier = session_id or str(uuid4())
        if not identifier:
            raise ValueError("session_id must not be empty")
        timezone_name = _validate_timezone(display_timezone)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO measurement_sessions (
                    id, status, started_at_utc, display_timezone, device_alias,
                    model_label, address_hash, requested_unit, condition,
                    capture_id, metadata_json
                ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    _timestamp(started_at, name="started_at"),
                    timezone_name,
                    device_alias,
                    model_label,
                    address_hash,
                    requested_unit,
                    condition,
                    capture_id,
                    _json_object(metadata, name="metadata"),
                ),
            )
        return identifier

    def _require_open(self, session_id: str) -> None:
        row = self._connection.execute(
            "SELECT status FROM measurement_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)
        if row["status"] != SessionStatus.OPEN.value:
            raise SessionClosedError(f"session {session_id} is {row['status']}")

    def append_frame(
        self,
        session_id: str,
        raw: bytes | bytearray | memoryview | str | DecodedFrame,
        *,
        observed_at: datetime | None = None,
        elapsed_ms: int | None = None,
        direction: str = "rx",
        characteristic_uuid: str | None = None,
    ) -> int:
        """Append one raw frame and return its zero-based session sequence.

        Malformed frames are retained with ``frame_kind='decode_error'`` and a
        diagnostic rather than discarded. Empty frames are preserved too.
        """

        if direction not in {"rx", "tx"}:
            raise ValueError("direction must be 'rx' or 'tx'")
        if elapsed_ms is not None and elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")
        observed_text = (
            None if observed_at is None else _timestamp(observed_at, name="observed_at")
        )

        decoded: DecodedFrame | None
        decode_error: str | None = None
        if isinstance(raw, DecodedFrame):
            decoded = raw
            raw_bytes = decoded.raw
        else:
            if isinstance(raw, str):
                try:
                    raw_bytes = bytes.fromhex(raw)
                except ValueError as exc:
                    raise ValueError("raw frame string must be hexadecimal") from exc
            else:
                raw_bytes = bytes(raw)
            try:
                decoded = decode_frame(raw_bytes)
            except FrameDecodeError as exc:
                decoded = None
                decode_error = str(exc)

        opcode = decoded.opcode if decoded is not None else (raw_bytes[0] if raw_bytes else None)
        kind = _frame_kind(decoded) if decoded is not None else "decode_error"
        checksum_valid = decoded.checksum_valid if decoded is not None else None
        fields = _decoded_fields(decoded) if decoded is not None else {}

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._require_open(session_id)
            row = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), -1) + 1 FROM frames WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            sequence = int(row[0])
            self._connection.execute(
                """
                INSERT INTO frames (
                    session_id, sequence, observed_at_utc, elapsed_ms, direction,
                    characteristic_uuid, raw, opcode, frame_kind, checksum_valid,
                    decoder_id, decoder_version, decoded_fields_json, decode_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    sequence,
                    observed_text,
                    elapsed_ms,
                    direction,
                    characteristic_uuid,
                    raw_bytes,
                    opcode,
                    kind,
                    None if checksum_valid is None else int(checksum_valid),
                    DECODER_ID,
                    DECODER_VERSION,
                    _json_object(fields, name="decoded fields"),
                    decode_error,
                ),
            )
            if isinstance(decoded, MeasurementFrame):
                self._insert_measurement(session_id, sequence, decoded)
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        return sequence

    def append_frames(
        self,
        session_id: str,
        frames: Iterable[bytes | bytearray | memoryview | str | DecodedFrame],
        *,
        direction: str = "rx",
        characteristic_uuid: str | None = None,
    ) -> list[int]:
        """Append frames in order, returning their assigned sequences."""

        return [
            self.append_frame(
                session_id,
                frame,
                direction=direction,
                characteristic_uuid=characteristic_uuid,
            )
            for frame in frames
        ]

    def _insert_measurement(
        self, session_id: str, sequence: int, frame: MeasurementFrame
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO measurement_frames (
                session_id, sequence, protocol_type, weight_raw_u16_be,
                weight_scale_divisor, weight_unit, weight_formula,
                weight_provenance, b5, b6, word_layout, word_provenance,
                opaque_unit_evidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                sequence,
                frame.protocol_type,
                frame.weight_raw_u16_be,
                frame.weight_scale_divisor,
                frame.weight_unit,
                frame.weight_formula,
                frame.weight_provenance,
                frame.b5,
                frame.b6,
                frame.word_layout,
                frame.word_provenance,
                frame.opaque_unit_evidence,
            ),
        )
        self._connection.executemany(
            """
            INSERT INTO word_values (
                session_id, frame_sequence, value_index, raw_value
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (session_id, sequence, index, value)
                for index, value in enumerate(frame.word_block)
            ),
        )

    def complete_session(
        self,
        session_id: str,
        *,
        ended_at: datetime,
        selected_frame_sequence: int | None = None,
        selection_policy_version: int | None = None,
        quality: MeasurementQuality | str = MeasurementQuality.INDETERMINATE,
        quality_reason: str | None = None,
        completion_reason: str | None = None,
    ) -> None:
        """Mark a session complete without conflating quality and lifecycle."""

        ended_text = _timestamp(ended_at, name="ended_at")
        quality_text = _quality_value(quality)
        if selected_frame_sequence is None and selection_policy_version is not None:
            raise ValueError("selection policy version requires a selected frame")
        if selected_frame_sequence is not None and selection_policy_version is None:
            raise ValueError("a selected frame requires a selection policy version")
        if (
            selected_frame_sequence is not None
            and selection_policy_version != WEIGHT_SELECTION_POLICY_VERSION
        ):
            raise ValueError("unsupported weight selection policy version")
        with self._connection:
            self._require_open(session_id)
            if selected_frame_sequence is not None:
                selected = self._connection.execute(
                    """
                    SELECT 1 FROM measurement_frames AS m
                    JOIN frames AS f
                      ON f.session_id = m.session_id AND f.sequence = m.sequence
                    WHERE m.session_id = ? AND m.sequence = ?
                      AND f.checksum_valid = 1
                    """,
                    (session_id, selected_frame_sequence),
                ).fetchone()
                if selected is None:
                    raise ValueError("selected frame must be a wire-valid measurement")
            self._connection.execute(
                """
                UPDATE measurement_sessions
                SET status = 'complete', ended_at_utc = ?, quality = ?,
                    quality_version = ?, quality_reason = ?, completion_reason = ?,
                    selected_frame_sequence = ?, selection_policy_version = ?
                WHERE id = ?
                """,
                (
                    ended_text,
                    quality_text,
                    QUALITY_VERSION,
                    quality_reason,
                    completion_reason,
                    selected_frame_sequence,
                    selection_policy_version,
                    session_id,
                ),
            )

    def abort_session(
        self,
        session_id: str,
        *,
        ended_at: datetime,
        quality: MeasurementQuality | str = MeasurementQuality.INDETERMINATE,
        quality_reason: str | None = None,
        completion_reason: str | None = None,
    ) -> None:
        """Close an incomplete acquisition without deleting its evidence."""

        ended_text = _timestamp(ended_at, name="ended_at")
        quality_text = _quality_value(quality)
        with self._connection:
            self._require_open(session_id)
            self._connection.execute(
                """
                UPDATE measurement_sessions
                SET status = 'aborted', ended_at_utc = ?, quality = ?,
                    quality_version = ?, quality_reason = ?, completion_reason = ?
                WHERE id = ?
                """,
                (
                    ended_text,
                    quality_text,
                    QUALITY_VERSION,
                    quality_reason,
                    completion_reason,
                    session_id,
                ),
            )

    @staticmethod
    def _session_summary(row: sqlite3.Row) -> MeasurementSessionSummary:
        started_at = _parse_timestamp(row["started_at_utc"])
        assert started_at is not None
        return MeasurementSessionSummary(
            id=row["id"],
            status=SessionStatus(row["status"]),
            started_at=started_at,
            ended_at=_parse_timestamp(row["ended_at_utc"]),
            display_timezone=row["display_timezone"],
            device_alias=row["device_alias"],
            model_label=row["model_label"],
            address_hash=row["address_hash"],
            requested_unit=row["requested_unit"],
            condition=row["condition"],
            capture_id=row["capture_id"],
            metadata=json.loads(row["metadata_json"]),
            quality=MeasurementQuality(row["quality"]),
            quality_version=row["quality_version"],
            quality_reason=row["quality_reason"],
            completion_reason=row["completion_reason"],
            selected_frame_sequence=row["selected_frame_sequence"],
            selection_policy_version=row["selection_policy_version"],
            frame_count=row["frame_count"],
            measurement_frame_count=row["measurement_frame_count"],
            decoder_versions=_decoder_versions(row["decoder_versions"]),
        )

    def get_session_summary(self, session_id: str) -> MeasurementSessionSummary:
        """Return session metadata and counts without loading frame bodies."""

        row = self._connection.execute(
            f"{_SESSION_SUMMARY_QUERY} WHERE s.id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)
        return self._session_summary(row)

    def get_latest_session_summary(self) -> MeasurementSessionSummary | None:
        """Return the newest session summary, or ``None`` when history is empty."""

        row = self._connection.execute(
            f"""
            {_SESSION_SUMMARY_QUERY}
            ORDER BY s.started_at_utc DESC, s.id DESC
            LIMIT 1
            """
        ).fetchone()
        return None if row is None else self._session_summary(row)

    def list_session_summaries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        after: tuple[datetime, str] | None = None,
    ) -> list[MeasurementSessionSummary]:
        """Return stable newest-first summaries without frame materialization.

        ``after`` is an internal keyset cursor containing the last returned
        ``(started_at, session_id)`` pair. Ordering by both columns prevents
        equal-timestamp sessions from being skipped or repeated.
        """

        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if after is not None and offset:
            raise ValueError("offset cannot be combined with an after cursor")

        if after is None:
            query = f"""
                {_SESSION_SUMMARY_QUERY}
                ORDER BY s.started_at_utc DESC, s.id DESC
                LIMIT ? OFFSET ?
            """
            parameters: tuple[Any, ...] = (limit, offset)
        else:
            after_started_at, after_session_id = after
            if not after_session_id:
                raise ValueError("after cursor session ID must not be empty")
            after_text = _timestamp(_aware(after_started_at, name="after"), name="after")
            query = f"""
                {_SESSION_SUMMARY_QUERY}
                WHERE (
                    s.started_at_utc < ?
                    OR (s.started_at_utc = ? AND s.id < ?)
                )
                ORDER BY s.started_at_utc DESC, s.id DESC
                LIMIT ?
            """
            parameters = (after_text, after_text, after_session_id, limit)

        rows = self._connection.execute(query, parameters).fetchall()
        return [self._session_summary(row) for row in rows]

    def get_session(self, session_id: str) -> MeasurementSession:
        row = self._connection.execute(
            "SELECT * FROM measurement_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)
        frames = self._load_frames(session_id)
        return MeasurementSession(
            id=row["id"],
            status=SessionStatus(row["status"]),
            started_at=_parse_timestamp(row["started_at_utc"]),  # type: ignore[arg-type]
            ended_at=_parse_timestamp(row["ended_at_utc"]),
            display_timezone=row["display_timezone"],
            device_alias=row["device_alias"],
            model_label=row["model_label"],
            address_hash=row["address_hash"],
            requested_unit=row["requested_unit"],
            condition=row["condition"],
            capture_id=row["capture_id"],
            metadata=json.loads(row["metadata_json"]),
            quality=MeasurementQuality(row["quality"]),
            quality_version=row["quality_version"],
            quality_reason=row["quality_reason"],
            completion_reason=row["completion_reason"],
            selected_frame_sequence=row["selected_frame_sequence"],
            selection_policy_version=row["selection_policy_version"],
            frames=frames,
        )

    def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[MeasurementSession]:
        """Return newest sessions first, including all retained frames.

        Use :meth:`list_session_summaries` for history projections that do not
        need the canonical evidence stream.
        """

        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        rows = self._connection.execute(
            """
            SELECT id FROM measurement_sessions
            ORDER BY started_at_utc DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [self.get_session(row["id"]) for row in rows]

    def list_sessions_since(
        self,
        *,
        since: datetime | None = None,
        after_session_id: str | None = None,
        limit: int = 100,
    ) -> list[MeasurementSession]:
        """Return sessions after a chronological `(started_at, id)` cursor."""

        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if since is None and after_session_id is not None:
            raise ValueError("after_session_id requires since")
        if since is None:
            rows = self._connection.execute(
                """
                SELECT id FROM measurement_sessions
                ORDER BY started_at_utc ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            since_text = _timestamp(_aware(since, name="since"), name="since")
            if after_session_id is None:
                predicate = "started_at_utc > ?"
                parameters: tuple[Any, ...] = (since_text, limit)
            else:
                predicate = "(started_at_utc > ? OR (started_at_utc = ? AND id > ?))"
                parameters = (since_text, since_text, after_session_id, limit)
            rows = self._connection.execute(
                f"""
                SELECT id FROM measurement_sessions
                WHERE {predicate}
                ORDER BY started_at_utc ASC, id ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self.get_session(row["id"]) for row in rows]

    def _load_frames(self, session_id: str) -> tuple[StoredFrame, ...]:
        rows = self._connection.execute(
            """
            SELECT f.*, m.protocol_type, m.weight_raw_u16_be,
                   m.weight_scale_divisor, m.weight_unit, m.weight_formula,
                   m.weight_provenance, m.b5, m.b6, m.word_layout,
                   m.word_provenance, m.opaque_unit_evidence
            FROM frames AS f
            LEFT JOIN measurement_frames AS m
              ON m.session_id = f.session_id AND m.sequence = f.sequence
            WHERE f.session_id = ?
            ORDER BY f.sequence
            """,
            (session_id,),
        ).fetchall()
        word_rows = self._connection.execute(
            """
            SELECT frame_sequence, raw_value FROM word_values
            WHERE session_id = ?
            ORDER BY frame_sequence, value_index
            """,
            (session_id,),
        ).fetchall()
        words: dict[int, list[int]] = {}
        for value in word_rows:
            words.setdefault(value["frame_sequence"], []).append(value["raw_value"])

        result: list[StoredFrame] = []
        for row in rows:
            measurement = None
            if row["weight_raw_u16_be"] is not None:
                measurement = StoredMeasurement(
                    protocol_type=row["protocol_type"],
                    weight_raw_u16_be=row["weight_raw_u16_be"],
                    weight_scale_divisor=row["weight_scale_divisor"],
                    weight_unit=row["weight_unit"],
                    weight_formula=row["weight_formula"],
                    weight_provenance=row["weight_provenance"],
                    b5=row["b5"],
                    b6=row["b6"],
                    word_block=tuple(words.get(row["sequence"], ())),
                    word_layout=row["word_layout"],
                    word_provenance=row["word_provenance"],
                    opaque_unit_evidence=row["opaque_unit_evidence"],
                )
            result.append(
                StoredFrame(
                    session_id=row["session_id"],
                    sequence=row["sequence"],
                    observed_at=_parse_timestamp(row["observed_at_utc"]),
                    elapsed_ms=row["elapsed_ms"],
                    direction=row["direction"],
                    characteristic_uuid=row["characteristic_uuid"],
                    raw=bytes(row["raw"]),
                    opcode=row["opcode"],
                    frame_kind=row["frame_kind"],
                    checksum_valid=(
                        None if row["checksum_valid"] is None else bool(row["checksum_valid"])
                    ),
                    decoder_id=row["decoder_id"],
                    decoder_version=row["decoder_version"],
                    decoded_fields=json.loads(row["decoded_fields_json"]),
                    decode_error=row["decode_error"],
                    measurement=measurement,
                )
            )
        return tuple(result)


__all__ = [
    "DEFAULT_DB_FILENAME",
    "DEFAULT_DISPLAY_TIMEZONE",
    "DeviceNotFoundError",
    "SCHEMA_REVISION",
    "OperationClosedError",
    "OperationNotFoundError",
    "SQLiteMeasurementStore",
    "SchemaRevisionError",
    "SessionClosedError",
    "SessionNotFoundError",
    "StorageError",
    "default_database_path",
]
