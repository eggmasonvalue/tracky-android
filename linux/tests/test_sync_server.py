"""Unit tests for the authenticated, read-only Android observation endpoint."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from tracky_mcp.protocol import append_checksum
from tracky_mcp.storage import SQLiteMeasurementStore
from tracky_mcp.sync_server import create_sync_handler, extract_session_telemetry

TOKEN = "test-token"


def _make_server(
    db_path: Any,
    auth_token: str | None = TOKEN,
) -> tuple[ThreadingHTTPServer, str]:
    handler = create_sync_handler(db_path=db_path, auth_token=auth_token)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


def _request(base_url: str, path: str, *, authenticated: bool = True) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {TOKEN}"} if authenticated else {}
    request = urllib.request.Request(f"{base_url}{path}", headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _create_sample_session(
    store: SQLiteMeasurementStore,
    session_time: datetime,
    *,
    session_id: str | None = None,
    select_weight: bool = True,
) -> str:
    p1 = append_checksum(
        bytes(
            (
                0x10, 0x12, 0x20, 0x1E, 0xD2, 0x01, 0x21,
                0x11, 0xC5, 0x10, 0x77, 0x08, 0x8E, 0x07, 0xF7, 0x00, 0x85,
            )
        )
    )
    p2 = append_checksum(
        bytes(
            (
                0x10, 0x12, 0x20, 0x1E, 0xD2, 0x01, 0x22,
                0x00, 0x74, 0x00, 0x8C, 0x00, 0x7A, 0x00, 0xE6, 0x00, 0xC8,
            )
        )
    )
    identifier = store.create_session(session_id=session_id, started_at=session_time)
    store.append_frames(identifier, [p1.hex(), p2.hex()])
    store.complete_session(
        identifier,
        ended_at=session_time,
        selected_frame_sequence=0 if select_weight else None,
        selection_policy_version=1 if select_weight else None,
    )
    return identifier


def test_projection_exposes_only_persisted_selection(tmp_path: Any) -> None:
    started = datetime(2026, 9, 13, 7, 0, 0, tzinfo=timezone.utc)
    p1 = append_checksum(
        bytes((0x10, 0x12, 0x20, 0x13, 0x88, 0x01, 0x21,
               0x01, 0x01, 0x02, 0x02, 0x03, 0x03, 0x04, 0x04, 0x05, 0x05))
    )
    p2 = append_checksum(
        bytes((0x10, 0x12, 0x20, 0x13, 0x88, 0x01, 0x22,
               0x06, 0x06, 0x07, 0x07, 0x08, 0x08, 0x09, 0x09, 0x0A, 0x0A))
    )

    with SQLiteMeasurementStore(tmp_path / "projection.db") as store:
        reversed_id = store.create_session(session_id="reversed", started_at=started)
        store.append_frames(reversed_id, (p2, p1))
        store.complete_session(reversed_id, ended_at=started)

        corrupt_id = store.create_session(session_id="corrupt", started_at=started)
        corrupt_p1 = bytearray(p1)
        corrupt_p1[-1] ^= 1
        store.append_frames(corrupt_id, (bytes(corrupt_p1), p2))
        store.complete_session(corrupt_id, ended_at=started)

        for session_id in (reversed_id, corrupt_id):
            projected = extract_session_telemetry(store.get_session(session_id))
            assert projected["selected"] is None


def test_handler_requires_a_token_and_health_is_authenticated(tmp_path: Any) -> None:
    with pytest.raises(ValueError, match="bearer token"):
        create_sync_handler(db_path=tmp_path / "missing.db")

    db_path = tmp_path / "test.db"
    with SQLiteMeasurementStore(db_path):
        pass
    server, base_url = _make_server(db_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _request(base_url, "/api/v1/health", authenticated=False)
        assert error.value.code == 401

        request = urllib.request.Request(
            f"{base_url}/api/v1/health",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 200
            assert "Access-Control-Allow-Origin" not in response.headers
            data = json.loads(response.read().decode("utf-8"))
            assert data["status"] == "ok"
    finally:
        server.shutdown()


def test_auth_protection_and_generic_client_errors(tmp_path: Any) -> None:
    db_path = tmp_path / "test.db"
    with SQLiteMeasurementStore(db_path):
        pass
    server, base_url = _make_server(db_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _request(base_url, "/api/v1/sessions/unsynced", authenticated=False)
        assert error.value.code == 401

        with pytest.raises(urllib.error.HTTPError) as error:
            _request(base_url, "/not-a-tracky-route")
        assert error.value.code == 404
        body = json.loads(error.value.read().decode("utf-8"))
        assert body == {"ok": False, "error": "not_found"}
    finally:
        server.shutdown()


def test_completed_selected_sessions_are_consumed_with_opaque_cursor(tmp_path: Any) -> None:
    db_path = tmp_path / "test.db"
    t1 = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 13, 9, 0, 0, tzinfo=timezone.utc)

    with SQLiteMeasurementStore(path=db_path) as store:
        s1_id = _create_sample_session(store, t1, session_id="session-1")
        s2_id = _create_sample_session(store, t2, session_id="session-2")

    server, base_url = _make_server(db_path)
    try:
        data = _request(base_url, "/api/v1/sessions/unsynced")
        assert data["contract_version"] == 1
        assert data["source_state"] == {"kind": "ready"}
        assert data["count"] == 2
        first = data["sessions"][0]
        assert first["session_id"] == s1_id
        assert first["selected"] == {
            "frame_sequence": 0,
            "weight": {
                "raw": 7890,
                "divisor": 100,
                "unit": "kg",
                "provenance": first["selected"]["weight"]["provenance"],
            },
        }
        assert data["next_cursor"]
        assert data["versions"]["selection_policy_version"] == 1

        query = urllib.parse.urlencode({"since": t1.isoformat()})
        since_data = _request(base_url, f"/api/v1/sessions/unsynced?{query}")
        assert since_data["count"] == 1
        assert since_data["sessions"][0]["session_id"] == s2_id
    finally:
        server.shutdown()


def test_equal_timestamp_cursor_does_not_skip_sessions(tmp_path: Any) -> None:
    db_path = tmp_path / "equal.db"
    started = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)
    with SQLiteMeasurementStore(path=db_path) as store:
        _create_sample_session(store, started, session_id="a")
        _create_sample_session(store, started, session_id="b")

    server, base_url = _make_server(db_path)
    try:
        first = _request(base_url, "/api/v1/sessions/unsynced?limit=1")
        cursor = urllib.parse.quote(first["next_cursor"], safe="")
        second = _request(base_url, f"/api/v1/sessions/unsynced?cursor={cursor}&limit=1")
        assert [first["sessions"][0]["session_id"], second["sessions"][0]["session_id"]] == [
            "a",
            "b",
        ]
    finally:
        server.shutdown()


def test_open_source_state_blocks_cursor_advance(tmp_path: Any) -> None:
    db_path = tmp_path / "open.db"
    started = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)
    with SQLiteMeasurementStore(path=db_path) as store:
        store.create_session(session_id="open", started_at=started)
        _create_sample_session(store, started.replace(hour=9), session_id="later")

    server, base_url = _make_server(db_path)
    try:
        data = _request(base_url, "/api/v1/sessions/unsynced")
        assert data["source_state"] == {
            "kind": "retryable",
            "code": "source_session_open",
        }
        assert data["sessions"] == []
        assert data["next_cursor"] is None
    finally:
        server.shutdown()
