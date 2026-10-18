"""Lossless SQLite storage tests using the sanitized CS10B fixtures."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from tracky_mcp.protocol import DECODER_ID, DECODER_VERSION, MeasurementQuality
from tracky_mcp.storage import (
    OperationStatus,
    SchemaRevisionError,
    SessionClosedError,
    SessionStatus,
    SQLiteMeasurementStore,
    default_database_path,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "cs10b"
CONDITION_FIXTURE = FIXTURE_ROOT / "20260809T194335Z" / "session.json"
REVISION3_SCHEMA = Path(__file__).parents[1] / "fixtures" / "storage" / "revision3.sql"
STARTED_AT = datetime(2026, 8, 9, 19, 43, 35, tzinfo=timezone.utc)


def _condition_fixture() -> dict:
    return json.loads(CONDITION_FIXTURE.read_text(encoding="utf-8"))


def test_default_database_path_honors_xdg_and_home() -> None:
    assert default_database_path(environ={"XDG_DATA_HOME": "/data"}) == Path(
        "/data/tracky-mcp/tracky.sqlite3"
    )
    assert default_database_path(environ={"HOME": "/home/alice"}) == Path(
        "/home/alice/.local/share/tracky-mcp/tracky.sqlite3"
    )


def test_revision_3_database_migrates_without_losing_canonical_evidence(tmp_path: Path) -> None:
    path = tmp_path / "revision3.sqlite3"
    raw_measurement = bytes.fromhex(
        "10122013880121010102020303040405051d"
    )
    raw_ack = bytes.fromhex("1f0620102176")
    started = "2026-08-09T19:43:35.000000Z"
    ended = "2026-08-09T19:43:45.000000Z"

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(REVISION3_SCHEMA.read_text(encoding="utf-8"))
    connection.execute("PRAGMA user_version = 3")
    connection.execute(
        """
        INSERT INTO known_devices (
            id, connection_target, connection_key, address_hash, advertised_name,
            first_seen_at_utc, last_seen_at_utc
        ) VALUES ('device-1', 'fixture-target', 'fixture-target', '000000000000',
                  'QN-Scale', ?, ?)
        """,
        (started, started),
    )
    connection.execute(
        """
        INSERT INTO measurement_sessions (
            id, status, started_at_utc, ended_at_utc, display_timezone,
            device_alias, model_label, address_hash, requested_unit, condition,
            capture_id, metadata_json
        ) VALUES ('session-1', 'open', ?, NULL, 'Asia/Kolkata', 'fixture',
                  'TR-CS10B', '000000000000', 'kg', 'migration',
                  'capture-1', '{"source":"revision3"}')
        """,
        (started,),
    )
    connection.execute(
        """
        INSERT INTO frames (
            session_id, sequence, observed_at_utc, elapsed_ms, direction,
            characteristic_uuid, raw, opcode, frame_kind, checksum_valid,
            decoder_id, decoder_version, decoded_fields_json, decode_error
        ) VALUES ('session-1', 0, ?, 0, 'rx', 'fff1', ?, 16, 'measurement', 1,
                  'tracky-cs10b-capture-layout', 1,
                  '{"resistance_raw":[257,514,771,1028,1285]}', NULL),
                 ('session-1', 1, ?, 1, 'tx', 'fff2', ?, 31, 'command', 1,
                  'tracky-cs10b-capture-layout', 1, '{}', NULL)
        """,
        (started, raw_measurement, started, raw_ack),
    )
    connection.execute(
        """
        INSERT INTO measurement_frames (
            session_id, sequence, protocol_type, weight_raw_u16_be,
            weight_scale_divisor, weight_unit, weight_formula,
            weight_provenance, b5, b6, resistance_layout, resistance_unit,
            resistance_provenance
        ) VALUES ('session-1', 0, 32, 5000, 100, 'kg',
                  'legacy formula', 'legacy provenance', 1, 33,
                  'legacy layout', 'legacy opaque unit evidence',
                  'legacy opaque provenance')
        """
    )
    connection.executemany(
        """
        INSERT INTO resistance_values (
            session_id, frame_sequence, value_index, raw_value
        ) VALUES ('session-1', 0, ?, ?)
        """,
        enumerate((257, 514, 771, 1028, 1285)),
    )
    connection.execute(
        """
        UPDATE measurement_sessions
        SET status = 'complete', ended_at_utc = ?, selected_frame_sequence = 0
        WHERE id = 'session-1'
        """,
        (ended,),
    )
    connection.execute(
        """
        INSERT INTO acquisition_operations (
            id, kind, status, created_at_utc, started_at_utc, finished_at_utc,
            session_id, metadata_json
        ) VALUES ('operation-1', 'weigh_in', 'complete', ?, ?, ?,
                  'session-1', '{"source":"revision3"}')
        """,
        (started, started, ended),
    )
    connection.commit()
    connection.close()

    with SQLiteMeasurementStore(path) as store:
        session = store.get_session("session-1")
        operation = store.get_operation("operation-1")
        revision = store._connection.execute("PRAGMA user_version").fetchone()[0]
        table_names = {
            row[0]
            for row in store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert revision == 5
    assert {"frames", "measurement_frames", "word_values"} <= table_names
    assert "resistance_values" not in table_names
    assert session.status is SessionStatus.COMPLETE
    assert session.quality is MeasurementQuality.INDETERMINATE
    assert session.selected_frame_sequence == 0
    assert [frame.raw for frame in session.frames] == [raw_measurement, raw_ack]
    assert session.frames[0].decoded_fields == {
        "resistance_raw": [257, 514, 771, 1028, 1285]
    }
    assert session.frames[0].measurement is not None
    assert session.frames[0].measurement.word_block == (257, 514, 771, 1028, 1285)
    assert session.frames[0].measurement.opaque_unit_evidence == "legacy opaque unit evidence"
    assert operation.status is OperationStatus.COMPLETE
    assert operation.metadata == {"source": "revision3"}


def test_fixture_session_round_trips_losslessly_without_selecting_stable_frame(
    tmp_path: Path,
) -> None:
    fixture = _condition_fixture()
    path = tmp_path / "tracky.sqlite3"

    with SQLiteMeasurementStore(path) as store:
        session_id = store.create_session(
            session_id="session-1",
            started_at=STARTED_AT,
            device_alias=fixture["device"]["alias"],
            model_label=fixture["device"]["model_label"],
            address_hash=fixture["device"]["address_hash"],
            requested_unit=fixture["unit"]["requested"],
            condition=fixture["condition"],
            capture_id=fixture["capture_id"],
            metadata={"fixture_schema_version": fixture["schema_version"]},
        )
        sequences = store.append_frames(
            session_id,
            (notification["hex"] for notification in fixture["notifications"]),
        )
        store.complete_session(
            session_id,
            ended_at=STARTED_AT + timedelta(seconds=15),
            quality=MeasurementQuality.ACCEPTED,
            quality_reason="stable_complete_word_burst",
            completion_reason="fixture_replay",
        )

        session = store.get_session(session_id)

    assert sequences == list(range(len(fixture["notifications"])))
    assert session.status is SessionStatus.COMPLETE
    assert session.quality is MeasurementQuality.ACCEPTED
    assert session.quality_version == 1
    assert session.quality_reason == "stable_complete_word_burst"
    assert session.completion_reason == "fixture_replay"
    assert session.selected_frame_sequence is None
    assert session.selected_frame is None
    assert session.display_timezone == "Asia/Kolkata"
    assert session.started_at_local.utcoffset() == timedelta(hours=5, minutes=30)
    assert session.metadata == {"fixture_schema_version": 1}
    assert [frame.raw_hex for frame in session.frames] == [
        notification["hex"] for notification in fixture["notifications"]
    ]
    assert len(session.measurements) == fixture["summary"]["measurement_count"]

    measurement = session.measurements[-1]
    assert measurement.decoder_id == DECODER_ID
    assert measurement.decoder_version == DECODER_VERSION
    assert measurement.measurement is not None
    assert measurement.measurement.weight_raw_u16_be == 7890
    assert measurement.measurement.weight_kg == Decimal("78.9")
    assert measurement.measurement.word_block == (4549, 4215, 2190, 2039, 133)
    assert "unproven" in measurement.measurement.word_provenance

    # The file is a durable system of record rather than an in-memory projection.
    with SQLiteMeasurementStore(path) as reopened:
        persisted = reopened.get_session(session_id)
    assert persisted == session


def test_quality_outcomes_round_trip_independently_of_session_status(tmp_path: Path) -> None:
    with SQLiteMeasurementStore(tmp_path / "quality.sqlite3") as store:
        for index, quality in enumerate(
            (
                MeasurementQuality.ACCEPTED,
                MeasurementQuality.CONTACT_FAILED,
                MeasurementQuality.INDETERMINATE,
            )
        ):
            session_id = store.create_session(
                session_id=f"quality-{index}",
                started_at=STARTED_AT + timedelta(seconds=index),
            )
            store.complete_session(
                session_id,
                ended_at=STARTED_AT + timedelta(seconds=index + 1),
                quality=quality,
                quality_reason=f"fixture-{quality.value}",
                completion_reason="policy",
            )

        sessions = [store.get_session(f"quality-{index}") for index in range(3)]

    assert [session.status for session in sessions] == [
        SessionStatus.COMPLETE,
        SessionStatus.COMPLETE,
        SessionStatus.COMPLETE,
    ]
    assert [session.quality for session in sessions] == [
        MeasurementQuality.ACCEPTED,
        MeasurementQuality.CONTACT_FAILED,
        MeasurementQuality.INDETERMINATE,
    ]
    assert all(session.selected_frame_sequence is None for session in sessions)


def test_selected_frame_must_reference_a_measurement(tmp_path: Path) -> None:
    fixture = _condition_fixture()
    with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
        session_id = store.create_session(started_at=STARTED_AT)
        info_sequence = store.append_frame(session_id, fixture["notifications"][0]["hex"])
        measurement_sequence = store.append_frame(
            session_id, fixture["notifications"][3]["hex"]
        )

        with pytest.raises(ValueError, match="wire-valid measurement"):
            store.complete_session(
                session_id,
                ended_at=STARTED_AT + timedelta(seconds=1),
                selected_frame_sequence=info_sequence,
                selection_policy_version=1,
            )

        store.complete_session(
            session_id,
            ended_at=STARTED_AT + timedelta(seconds=1),
            selected_frame_sequence=measurement_sequence,
            selection_policy_version=1,
        )
        session = store.get_session(session_id)

    assert session.selected_frame == session.frames[measurement_sequence]
    assert session.selected_frame.measurement is not None


def test_malformed_and_empty_frames_are_retained(tmp_path: Path) -> None:
    with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
        session_id = store.create_session(started_at=STARTED_AT)
        short_sequence = store.append_frame(session_id, bytes.fromhex("1001"))
        empty_sequence = store.append_frame(session_id, b"")
        session = store.get_session(session_id)

    short = session.frames[short_sequence]
    assert short.raw == bytes.fromhex("1001")
    assert short.opcode == 0x10
    assert short.frame_kind == "decode_error"
    assert "must be 18 bytes" in (short.decode_error or "")

    empty = session.frames[empty_sequence]
    assert empty.raw == b""
    assert empty.opcode is None
    assert empty.frame_kind == "decode_error"
    assert "empty frame" in (empty.decode_error or "")


def test_closed_session_preserves_frames_and_rejects_append(tmp_path: Path) -> None:
    with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
        session_id = store.create_session(started_at=STARTED_AT)
        store.append_frame(session_id, bytes.fromhex("ff00"))
        store.abort_session(session_id, ended_at=STARTED_AT + timedelta(seconds=1))

        with pytest.raises(SessionClosedError):
            store.append_frame(session_id, bytes.fromhex("ff01"))

        session = store.get_session(session_id)

    assert session.status is SessionStatus.ABORTED
    assert session.quality is MeasurementQuality.INDETERMINATE
    assert [frame.raw_hex for frame in session.frames] == ["ff00"]


def test_timestamps_must_be_aware_and_session_end_cannot_precede_start(
    tmp_path: Path,
) -> None:
    with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
        with pytest.raises(ValueError, match="timezone"):
            store.create_session(started_at=datetime(2026, 8, 9))

        session_id = store.create_session(started_at=STARTED_AT)
        with pytest.raises(sqlite3.IntegrityError):
            store.complete_session(session_id, ended_at=STARTED_AT - timedelta(seconds=1))


def test_unknown_schema_revision_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 999")
    connection.close()

    with pytest.raises(SchemaRevisionError, match="999"):
        SQLiteMeasurementStore(path)


def test_list_sessions_is_newest_first(tmp_path: Path) -> None:
    with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
        older = store.create_session(session_id="older", started_at=STARTED_AT)
        newer = store.create_session(
            session_id="newer", started_at=STARTED_AT + timedelta(days=1)
        )

        sessions = store.list_sessions(limit=1)

    assert [session.id for session in sessions] == [newer]
    assert older != newer


def test_read_only_store_can_query_wal_but_cannot_mutate(tmp_path: Path) -> None:
    path = tmp_path / "read-only.sqlite3"
    with SQLiteMeasurementStore(path) as writable:
        journal_mode = writable._connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode == "wal"
        session_id = writable.create_session(session_id="read-only", started_at=STARTED_AT)
        writable.complete_session(session_id, ended_at=STARTED_AT + timedelta(seconds=1))

        # Read-only MCP access must work while the daemon-owned writer still
        # has the WAL open, and all attempted mutations must fail at SQLite.
        with SQLiteMeasurementStore(path, read_only=True) as store:
            assert store.get_session_summary(session_id).id == session_id
            with pytest.raises(sqlite3.OperationalError):
                store.create_session(started_at=STARTED_AT)


def test_session_summary_queries_do_not_load_frame_streams(tmp_path: Path) -> None:
    fixture = _condition_fixture()
    with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
        session_id = store.create_session(session_id="summary", started_at=STARTED_AT)
        store.append_frames(
            session_id,
            (notification["hex"] for notification in fixture["notifications"]),
        )
        store.complete_session(session_id, ended_at=STARTED_AT + timedelta(seconds=1))

        def fail_if_loaded(_session_id: str) -> None:
            raise AssertionError("summary query loaded frame bodies")

        original_loader = store._load_frames
        store._load_frames = fail_if_loaded  # type: ignore[method-assign]
        try:
            summaries = store.list_session_summaries(limit=10)
            latest = store.get_latest_session_summary()
            selected = store.get_session_summary(session_id)
        finally:
            store._load_frames = original_loader  # type: ignore[method-assign]

    assert latest is not None
    assert summaries[0] == latest == selected
    assert latest.frame_count == len(fixture["notifications"])
    assert latest.measurement_frame_count == fixture["summary"]["measurement_count"]
