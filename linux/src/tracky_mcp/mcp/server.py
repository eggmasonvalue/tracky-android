"""On-demand, read-only MCP projection over Tracky history."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from tracky_mcp import __version__
from tracky_mcp.storage import (
    MeasurementSessionSummary,
    SessionNotFoundError,
    SQLiteMeasurementStore,
)

from .views import (
    ErrorDetail,
    FramesResource,
    SessionList,
    SessionResource,
    SessionSummary,
)

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

Limit = Annotated[int, Field(ge=1, le=100)]
SessionId = Annotated[str, Field(min_length=1, max_length=128)]
Cursor = Annotated[str, Field(min_length=1, max_length=256)]
_CURSOR_PREFIX = "s1."
_NO_SESSIONS_MESSAGE = "No captured measurement sessions are available"
_SESSION_NOT_FOUND_MESSAGE = "Measurement session was not found"
_INVALID_CURSOR_MESSAGE = "The session cursor is invalid"


def _error_detail(
    code: str,
    message: str,
    *,
    session_id: str | None = None,
) -> ErrorDetail:
    return ErrorDetail(code=code, message=message, session_id=session_id)


def _encode_cursor(session: MeasurementSessionSummary) -> str:
    payload = {
        "v": 1,
        "started_at": session.started_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "session_id": session.id,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"{_CURSOR_PREFIX}{encoded.rstrip('=')}"


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    if not cursor.startswith(_CURSOR_PREFIX):
        raise ValueError("unsupported cursor version")
    encoded = cursor[len(_CURSOR_PREFIX) :]
    if not encoded:
        raise ValueError("empty cursor payload")
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        started_at = datetime.fromisoformat(str(payload["started_at"]).replace("Z", "+00:00"))
        session_id = str(payload["session_id"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed cursor payload") from exc
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("cursor timestamp must be timezone-aware")
    if not session_id or len(session_id) > 128 or payload.get("v") != 1:
        raise ValueError("invalid cursor fields")
    return started_at, session_id


def _not_found(session_id: str) -> ErrorDetail:
    return _error_detail(
        "session_not_found",
        _SESSION_NOT_FOUND_MESSAGE,
        session_id=session_id,
    )


def create_server(store: SQLiteMeasurementStore) -> MCPServer:
    """Build the read-only MCP projection without acquiring or recovering work.

    Acquisition ownership stays with the Linux daemon. This function only
    registers history tools and session/frame resources; it never constructs an
    acquisition service or performs operation recovery.
    """

    server = MCPServer(
        "tracky-mcp",
        title="Tracky read-only measurement history",
        description="On-demand read-only CS10B session history and wire evidence.",
        instructions=(
            "Read captured history only. Treat raw frames as evidence and decoded values "
            "as interpretations. Quality is a separate versioned field, and selected "
            "weight is present only when the contract supplies it. Keep opaque word blocks "
            "unassigned to units, channels, frequencies, or physiological meaning."
        ),
        version=__version__,
    )

    @server.tool(annotations=_READ_ONLY)
    async def list_sessions(limit: Limit = 20, cursor: Cursor | None = None) -> SessionList:
        """List bounded newest-first summaries using an opaque continuation cursor."""

        after: tuple[datetime, str] | None = None
        if cursor is not None:
            try:
                after = _decode_cursor(cursor)
            except ValueError:
                return SessionList(
                    ok=False,
                    error=_error_detail("invalid_cursor", _INVALID_CURSOR_MESSAGE),
                )

        sessions = store.list_session_summaries(limit=limit + 1, after=after)
        has_more = len(sessions) > limit
        page = sessions[:limit]
        next_cursor = _encode_cursor(page[-1]) if has_more and page else None
        return SessionList(
            sessions=[SessionSummary.from_record(session) for session in page],
            next_cursor=next_cursor,
        )

    @server.tool(annotations=_READ_ONLY)
    async def get_latest_session() -> SessionResource:
        """Return metadata for the newest captured session or a stable empty result."""

        session = store.get_latest_session_summary()
        if session is None:
            return SessionResource(
                ok=False,
                error=_error_detail("no_sessions", _NO_SESSIONS_MESSAGE),
            )
        return SessionResource.from_record(session)

    @server.tool(annotations=_READ_ONLY)
    async def get_session(session_id: SessionId) -> SessionResource:
        """Return one session's metadata or a stable not-found result."""

        try:
            session = store.get_session_summary(session_id)
        except SessionNotFoundError:
            return SessionResource(ok=False, error=_not_found(session_id))
        return SessionResource.from_record(session)

    @server.tool(annotations=_READ_ONLY)
    async def get_session_evidence(session_id: SessionId) -> FramesResource:
        """Return one session's complete ordered wire evidence or a stable error."""

        try:
            session = store.get_session(session_id)
        except SessionNotFoundError:
            return FramesResource(ok=False, error=_not_found(session_id))
        return FramesResource.from_record(session)

    @server.resource(
        "tracky://sessions/{session_id}",
        mime_type="application/json",
        description="Measurement-session metadata and evidence counts, excluding frame bodies.",
    )
    async def session_resource(session_id: str) -> str:
        try:
            session = store.get_session_summary(session_id)
        except SessionNotFoundError:
            return SessionResource(ok=False, error=_not_found(session_id)).model_dump_json()
        return SessionResource.from_record(session).model_dump_json()

    @server.resource(
        "tracky://sessions/{session_id}/frames",
        mime_type="application/json",
        description="Complete ordered RX/TX evidence stream for a measurement session.",
    )
    async def frames_resource(session_id: str) -> str:
        try:
            session = store.get_session(session_id)
        except SessionNotFoundError:
            return FramesResource(ok=False, error=_not_found(session_id)).model_dump_json()
        return FramesResource.from_record(session).model_dump_json()

    return server


__all__ = ["create_server"]
