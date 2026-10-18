"""Mainstream MCP client tests for the read-only history projection."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MethodType
from typing import Any

from mcp import Client

from tracky_mcp.mcp import create_server
from tracky_mcp.protocol import MeasurementQuality
from tracky_mcp.storage import SQLiteMeasurementStore

NOW = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "cs10b"
    / "conditions"
    / "handle_contact_complete.json"
)
FOOT_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "cs10b"
    / "conditions"
    / "foot_only_contact_failed.json"
)
REVISION3_SCHEMA = Path(__file__).parents[1] / "fixtures" / "storage" / "revision3.sql"


def _seed_raw_session(
    store: SQLiteMeasurementStore,
    session_id: str,
    frames: list[str | bytes],
) -> str:
    store.create_session(
        session_id=session_id,
        started_at=NOW,
        requested_unit="kg",
        condition="fixture",
        capture_id=f"{session_id}-capture",
    )
    store.append_frames(session_id, frames)
    store.complete_session(
        session_id,
        ended_at=NOW + timedelta(seconds=1),
    )
    return session_id


def _seed_session(store: SQLiteMeasurementStore) -> str:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    session_id = store.create_session(
        session_id="session-1",
        started_at=NOW,
        device_alias="fixture-scale",
        model_label="TR-CS10B",
        address_hash="000000000000",
        requested_unit="kg",
        condition=fixture["condition"],
        capture_id=fixture["fixture_id"],
    )
    store.append_frames(session_id, fixture["notifications"])
    store.complete_session(
        session_id,
        ended_at=NOW + timedelta(seconds=15),
        quality=MeasurementQuality.ACCEPTED,
        quality_reason="fixture_quality",
        completion_reason="fixture_replay",
    )
    return session_id


def _seed_revision3_database(path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw_measurement = bytes.fromhex(fixture["notifications"][3])
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(REVISION3_SCHEMA.read_text(encoding="utf-8"))
    connection.execute("PRAGMA user_version = 3")
    started = "2026-08-11T18:00:00.000000Z"
    ended = "2026-08-11T18:00:01.000000Z"
    connection.execute(
        """
        INSERT INTO measurement_sessions (
            id, status, started_at_utc, ended_at_utc, display_timezone,
            requested_unit, condition, capture_id, metadata_json
        ) VALUES ('legacy-session', 'complete', ?, ?, 'Asia/Kolkata',
                  'kg', 'legacy', 'legacy-capture', '{}')
        """,
        (started, ended),
    )
    connection.execute(
        """
        INSERT INTO frames (
            session_id, sequence, observed_at_utc, elapsed_ms, direction,
            characteristic_uuid, raw, opcode, frame_kind, checksum_valid,
            decoder_id, decoder_version, decoded_fields_json, decode_error
        ) VALUES ('legacy-session', 0, ?, 0, 'rx', 'fff1', ?, 16,
                  'measurement', 1, 'legacy-decoder', 1,
                  '{\"resistance_raw\":[257,514,771,1028,1285],\"resistance_unit\":\"unknown\"}',
                  NULL)
        """,
        (started, raw_measurement),
    )
    connection.execute(
        """
        INSERT INTO measurement_frames (
            session_id, sequence, protocol_type, weight_raw_u16_be,
            weight_scale_divisor, weight_unit, weight_formula,
            weight_provenance, b5, b6, resistance_layout, resistance_unit,
            resistance_provenance
        ) VALUES ('legacy-session', 0, 32, 5000, 100, 'kg',
                  'legacy formula', 'legacy provenance', 1, 33,
                  'legacy layout', 'legacy opaque unit evidence',
                  'legacy opaque provenance')
        """
    )
    connection.executemany(
        """
        INSERT INTO resistance_values (
            session_id, frame_sequence, value_index, raw_value
        ) VALUES ('legacy-session', 0, ?, ?)
        """,
        enumerate((257, 514, 771, 1028, 1285)),
    )
    connection.commit()
    connection.close()


def test_read_only_mcp_surface_has_tool_equivalents_for_history_resources(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            session_id = _seed_session(store)
            server = create_server(store)

            # The history tools and metadata resource must not materialize the
            # canonical frame stream. The evidence operation is tested after
            # restoring the loader below.
            original_loader = store._load_frames

            def fail_if_frames_are_loaded(_self: Any, _session_id: str) -> tuple[Any, ...]:
                raise AssertionError("summary path loaded the full frame stream")

            store._load_frames = MethodType(fail_if_frames_are_loaded, store)  # type: ignore[method-assign]
            async with Client(server, mode="2026-07-28") as client:
                assert client.protocol_version == "2026-07-28"
                listed_tools = await client.list_tools()
                tool_names = {tool.name for tool in listed_tools.tools}
                assert tool_names == {
                    "list_sessions",
                    "get_latest_session",
                    "get_session",
                    "get_session_evidence",
                }

                listed = await client.call_tool("list_sessions", {"limit": 10})
                assert listed.is_error is False
                assert listed.structured_content is not None
                assert listed.structured_content["contract_version"] == 1
                [summary] = listed.structured_content["sessions"]
                assert summary["id"] == session_id
                assert summary["session_id"] == session_id
                assert summary["frame_count"] == 9
                assert summary["measurement_frame_count"] == 6
                assert summary["quality"] == "accepted"
                assert summary["versions"]["quality_version"] == 1

                latest = await client.call_tool("get_latest_session", {})
                detail = await client.call_tool("get_session", {"session_id": session_id})
                assert latest.is_error is False
                assert detail.is_error is False
                assert latest.structured_content == detail.structured_content
                assert detail.structured_content is not None
                assert detail.structured_content["session_id"] == session_id
                assert detail.structured_content["summary"]["frame_count"] == 9
                assert detail.structured_content["raw_frames"] == {
                    "resource_uri": f"tracky://sessions/{session_id}/frames",
                    "count": 9,
                }

                resource = await client.read_resource(f"tracky://sessions/{session_id}")
                resource_payload = json.loads(resource.contents[0].text)
                assert resource_payload == detail.structured_content

                store._load_frames = original_loader  # type: ignore[method-assign]
                evidence = await client.call_tool(
                    "get_session_evidence", {"session_id": session_id}
                )
                assert evidence.is_error is False
                assert evidence.structured_content is not None
                assert evidence.structured_content["session_id"] == session_id
                assert len(evidence.structured_content["frames"]) == 9
                assert evidence.structured_content["opaque_block_a"] == [
                    257,
                    514,
                    771,
                    1028,
                    1285,
                ]
                assert evidence.structured_content["opaque_block_b"] == [
                    1542,
                    1799,
                    2056,
                    2313,
                    2570,
                ]
                measurement = next(
                    frame["measurement"]
                    for frame in evidence.structured_content["frames"]
                    if frame["measurement"] is not None
                )
                assert measurement["opaque_words"] == [257, 514, 771, 1028, 1285]
                assert measurement["weight"]["raw"] == 5000

                frames_resource = await client.read_resource(
                    f"tracky://sessions/{session_id}/frames"
                )
                frames_payload = json.loads(frames_resource.contents[0].text)
                assert frames_payload == evidence.structured_content

    asyncio.run(scenario())


def test_aggregate_blocks_require_wire_valid_ordered_bursts(tmp_path: Path) -> None:
    async def scenario() -> None:
        handle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        foot = json.loads(FOOT_FIXTURE.read_text(encoding="utf-8"))
        packet1 = handle["notifications"][3]
        packet2 = handle["notifications"][6]
        interrupted = handle["notifications"][0]
        zero_packet1 = foot["notifications"][3]
        corrupt_packet1 = bytearray.fromhex(packet1)
        corrupt_packet1[-1] ^= 1

        cases = {
            "corrupt": [bytes(corrupt_packet1), packet2],
            "interrupted": [packet1, interrupted, packet2],
            # A second burst starts but never supplies packet 2. The aggregate
            # must remain the first completed pair rather than cross-pairing.
            "multi": [packet1, packet2, zero_packet1],
        }
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            for session_id, frames in cases.items():
                _seed_raw_session(store, session_id, frames)
            server = create_server(store)
            async with Client(server, mode="2026-07-28") as client:
                for session_id in ("corrupt", "interrupted"):
                    result = await client.call_tool(
                        "get_session_evidence", {"session_id": session_id}
                    )
                    assert result.structured_content is not None
                    assert result.structured_content["opaque_block_a"] is None
                    assert result.structured_content["opaque_block_b"] is None

                result = await client.call_tool(
                    "get_session_evidence", {"session_id": "multi"}
                )
                assert result.structured_content is not None
                assert result.structured_content["opaque_block_a"] == handle[
                    "opaque_block_a"
                ]
                assert result.structured_content["opaque_block_b"] == handle[
                    "opaque_block_b"
                ]

    asyncio.run(scenario())


def test_read_only_mcp_projects_migrated_evidence_without_legacy_semantics(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        path = tmp_path / "revision3.sqlite3"
        _seed_revision3_database(path)
        with SQLiteMeasurementStore(path) as migrated:
            stored = migrated.get_session("legacy-session")
            assert stored.frames[0].decoded_fields["resistance_raw"] == [
                257,
                514,
                771,
                1028,
                1285,
            ]

        with SQLiteMeasurementStore(path, read_only=True) as store:
            server = create_server(store)
            async with Client(server, mode="2026-07-28") as client:
                result = await client.call_tool(
                    "get_session_evidence", {"session_id": "legacy-session"}
                )
                assert result.is_error is False
                assert result.structured_content is not None
                decoded = result.structured_content["frames"][0]["decoded_fields"]
                assert decoded["opaque_words"] == [257, 514, 771, 1028, 1285]
                assert "resistance_raw" not in decoded
                assert "resistance_unit" not in decoded
                assert "resistance" not in json.dumps(decoded).lower()

    asyncio.run(scenario())


def test_session_cursor_pages_equal_timestamps_without_skips(tmp_path: Path) -> None:
    async def scenario() -> None:
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            for index in range(5):
                _seed_raw_session(store, f"session-{index}", [])
            server = create_server(store)
            async with Client(server, mode="2026-07-28") as client:
                cursor = None
                pages: list[list[str]] = []
                for expected in (
                    ["session-4", "session-3"],
                    ["session-2", "session-1"],
                    ["session-0"],
                ):
                    arguments = {"limit": 2}
                    if cursor is not None:
                        arguments["cursor"] = cursor
                    result = await client.call_tool("list_sessions", arguments)
                    assert result.structured_content is not None
                    page = result.structured_content
                    pages.append([item["session_id"] for item in page["sessions"]])
                    assert pages[-1] == expected
                    cursor = page["next_cursor"]
                assert cursor is None
                assert [session_id for page in pages for session_id in page] == [
                    f"session-{index}" for index in range(4, -1, -1)
                ]

    asyncio.run(scenario())


def test_mixed_decoder_versions_are_not_collapsed_to_maximum(tmp_path: Path) -> None:
    async def scenario() -> None:
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            session_id = _seed_session(store)
            current_version = store._connection.execute(
                "SELECT decoder_version FROM frames WHERE session_id = ? LIMIT 1",
                (session_id,),
            ).fetchone()[0]
            store._connection.execute(
                "UPDATE frames SET decoder_version = ? WHERE session_id = ? AND sequence = 0",
                (current_version + 1, session_id),
            )
            store._connection.commit()
            server = create_server(store)
            async with Client(server, mode="2026-07-28") as client:
                result = await client.call_tool("get_session", {"session_id": session_id})
                assert result.structured_content is not None
                versions = result.structured_content["versions"]
                assert versions["decoder_version"] is None
                assert versions["decoder_versions"] == sorted(
                    {current_version, current_version + 1}
                )

    asyncio.run(scenario())


def test_structured_empty_missing_and_invalid_cursor_outcomes(tmp_path: Path) -> None:
    async def scenario() -> None:
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            server = create_server(store)
            async with Client(server, mode="2026-07-28") as client:
                latest = await client.call_tool("get_latest_session", {})
                assert latest.is_error is False
                assert latest.structured_content is not None
                assert latest.structured_content["ok"] is False
                assert latest.structured_content["error"] == {
                    "code": "no_sessions",
                    "message": "No captured measurement sessions are available",
                    "session_id": None,
                }
                missing = await client.call_tool(
                    "get_session", {"session_id": "missing-session"}
                )
                assert missing.structured_content is not None
                assert missing.structured_content["ok"] is False
                assert missing.structured_content["error"] == {
                    "code": "session_not_found",
                    "message": "Measurement session was not found",
                    "session_id": "missing-session",
                }
                evidence = await client.call_tool(
                    "get_session_evidence", {"session_id": "missing-session"}
                )
                assert evidence.structured_content is not None
                assert evidence.structured_content["error"]["code"] == "session_not_found"
                invalid = await client.call_tool(
                    "list_sessions", {"limit": 1, "cursor": "not-a-cursor"}
                )
                assert invalid.structured_content is not None
                assert invalid.structured_content["error"]["code"] == "invalid_cursor"

                resource = await client.read_resource("tracky://sessions/missing-session")
                assert json.loads(resource.contents[0].text)["error"]["code"] == (
                    "session_not_found"
                )

    asyncio.run(scenario())


def test_read_only_tools_are_bounded_and_annotated(tmp_path: Path) -> None:
    async def scenario() -> None:
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            server = create_server(store)
            async with Client(server, mode="2026-07-28") as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                assert set(tools) == {
                    "list_sessions",
                    "get_latest_session",
                    "get_session",
                    "get_session_evidence",
                }
                for tool in tools.values():
                    assert tool.output_schema is not None
                    assert tool.annotations is not None
                    assert tool.annotations.read_only_hint is True
                    assert tool.annotations.destructive_hint is False
                    assert tool.annotations.open_world_hint is False

                assert tools["list_sessions"].input_schema["properties"]["limit"][
                    "maximum"
                ] == 100
                assert tools["get_session"].input_schema["properties"]["session_id"][
                    "maxLength"
                ] == 128

    asyncio.run(scenario())
