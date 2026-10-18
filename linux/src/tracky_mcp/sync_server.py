"""Authenticated, read-only Android observation projection.

The Android bridge consumes only completed Linux sessions and the explicitly
persisted weight-selection result. Acquisition owns the writable database;
this process opens it read-only. The default listener is loopback. Production
use requires either a certificate/key pair or an explicitly configured secure
external TLS terminator in front of the loopback listener.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import logging
import os
import ssl
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from tracky_mcp.protocol import (
    DECODER_VERSION,
    QUALITY_VERSION,
    WEIGHT_SELECTION_POLICY_VERSION,
)
from tracky_mcp.protocol.burst import BurstAssembler
from tracky_mcp.protocol.decode import MeasurementFrame, decode_frame
from tracky_mcp.storage import (
    MeasurementSession,
    SessionStatus,
    SQLiteMeasurementStore,
)

logger = logging.getLogger("tracky.sync_server")

CONTRACT_VERSION = 1
TRANSPORT_VERSION = 1
_CURSOR_PREFIX = "s1."
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000
_MAX_TOKEN_LENGTH = 4096


def _validate_token(token: str | None) -> str:
    value = (token or "").strip()
    if not value or len(value) > _MAX_TOKEN_LENGTH:
        raise ValueError("a non-empty bearer token is required")
    if any(character.isspace() or not character.isprintable() for character in value):
        raise ValueError("the bearer token contains invalid characters")
    return value


def _read_token_file(path: str | os.PathLike[str]) -> str:
    try:
        return _validate_token(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError("unable to read the sync token file") from exc


def _encode_cursor(session: MeasurementSession) -> str:
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
    padded = encoded + "=" * (-len(encoded) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    started_at = datetime.fromisoformat(str(payload["started_at"]).replace("Z", "+00:00"))
    session_id = str(payload["session_id"])
    if payload.get("v") != 1 or not session_id:
        raise ValueError("invalid cursor fields")
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("cursor timestamp must be timezone-aware")
    return started_at, session_id


def _versions(session: MeasurementSession) -> dict[str, Any]:
    decoder_versions = sorted({frame.decoder_version for frame in session.frames}) or [
        DECODER_VERSION
    ]
    return {
        "transport_version": TRANSPORT_VERSION,
        "decoder_version": decoder_versions[0] if len(decoder_versions) == 1 else None,
        "decoder_versions": decoder_versions,
        "selection_policy_version": WEIGHT_SELECTION_POLICY_VERSION,
        "quality_version": session.quality_version,
    }


def _selected_weight(session: MeasurementSession) -> dict[str, Any] | None:
    """Expose only Linux's persisted, policy-versioned selected frame."""

    if (
        session.status is not SessionStatus.COMPLETE
        or session.ended_at is None
        or session.selection_policy_version != WEIGHT_SELECTION_POLICY_VERSION
    ):
        return None
    frame = session.selected_frame
    if frame is None or frame.checksum_valid is not True or frame.measurement is None:
        return None
    measurement = frame.measurement
    return {
        "frame_sequence": frame.sequence,
        "weight": {
            "raw": measurement.weight_raw_u16_be,
            "divisor": measurement.weight_scale_divisor,
            "unit": measurement.weight_unit,
            "provenance": measurement.weight_provenance,
        },
    }


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


def extract_session_telemetry(session: MeasurementSession) -> dict[str, Any]:
    """Project session metadata, selected weight frame, and opaque burst blocks."""

    block_a, block_b = _opaque_blocks(session)
    return {
        "contract_version": CONTRACT_VERSION,
        "session_id": session.id,
        "started_at_utc": session.started_at.isoformat(),
        "status": session.status.value,
        "quality": session.quality.value,
        "quality_version": session.quality_version,
        "selection_policy_version": WEIGHT_SELECTION_POLICY_VERSION,
        "selected": _selected_weight(session),
        "opaque_block_a": block_a,
        "opaque_block_b": block_b,
        "device_alias": session.device_alias,
        "versions": _versions(session),
    }


def _page_versions(sessions: list[MeasurementSession]) -> dict[str, Any]:
    decoder_versions = sorted(
        {frame.decoder_version for session in sessions for frame in session.frames}
    )
    quality_versions = {session.quality_version for session in sessions}
    return {
        "transport_version": TRANSPORT_VERSION,
        "decoder_version": decoder_versions[0] if len(decoder_versions) == 1 else None,
        "decoder_versions": decoder_versions or [DECODER_VERSION],
        "selection_policy_version": WEIGHT_SELECTION_POLICY_VERSION,
        "quality_version": (
            next(iter(quality_versions))
            if len(quality_versions) == 1
            else QUALITY_VERSION
        ),
    }


def _page_body(
    sessions: list[MeasurementSession],
    *,
    next_cursor: str | None,
    source_state: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "versions": _page_versions(sessions),
        "source_state": source_state or {"kind": "ready"},
        "count": len(sessions),
        "next_cursor": next_cursor,
        "sessions": [extract_session_telemetry(session) for session in sessions],
    }


def create_sync_handler(
    db_path: str | os.PathLike[str] | None = None,
    auth_token: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a handler with mandatory bearer authentication."""

    token = _validate_token(auth_token)

    class SyncRequestHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: HTTPStatus, body: Any) -> None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _send_error(self, status: HTTPStatus, code: str) -> None:
            self._send_json(status, {"ok": False, "error": code})

        def _check_auth(self) -> bool:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return False
            supplied = header[len("Bearer ") :]
            return bool(supplied) and hmac.compare_digest(supplied, token)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if not self._check_auth():
                self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized")
                return

            if path == "/api/v1/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "status": "ok",
                        "service": "tracky-sync",
                        "contract_version": CONTRACT_VERSION,
                    },
                )
                return

            if path != "/api/v1/sessions/unsynced":
                self._send_error(HTTPStatus.NOT_FOUND, "not_found")
                return

            params = parse_qs(parsed.query, keep_blank_values=True)
            cursor_values = params.get("cursor", [])
            since_values = params.get("since", [])
            if cursor_values and since_values:
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request")
                return
            cursor_str = cursor_values[0] if cursor_values else None
            since_str = since_values[0] if since_values else None
            limit_str = params.get("limit", [str(_DEFAULT_LIMIT)])[0]
            try:
                limit = int(limit_str)
                if not 1 <= limit <= _MAX_LIMIT:
                    raise ValueError
            except ValueError:
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request")
                return

            since: datetime | None = None
            after_session_id: str | None = None
            if cursor_str:
                try:
                    since, after_session_id = _decode_cursor(cursor_str)
                except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                    self._send_error(HTTPStatus.BAD_REQUEST, "invalid_cursor")
                    return
            elif since_str:
                try:
                    clean_since = since_str.replace(" ", "+")
                    since = datetime.fromisoformat(clean_since)
                    if since.tzinfo is None:
                        since = since.replace(tzinfo=timezone.utc)
                except ValueError:
                    self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request")
                    return

            try:
                with SQLiteMeasurementStore(path=db_path, read_only=True) as store:
                    sessions = store.list_sessions_since(
                        since=since,
                        after_session_id=after_session_id,
                        limit=limit,
                    )
            except Exception:
                logger.exception("read-only sync query failed")
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error")
                return

            # Never move past an open source session. The Android worker must
            # retry this page after acquisition closes it; later sessions are
            # deliberately withheld rather than silently skipped.
            if any(session.status is SessionStatus.OPEN for session in sessions):
                self._send_json(
                    HTTPStatus.OK,
                    _page_body(
                        [],
                        next_cursor=None,
                        source_state={"kind": "retryable", "code": "source_session_open"},
                    ),
                )
                return

            next_cursor = _encode_cursor(sessions[-1]) if sessions else cursor_str
            self._send_json(
                HTTPStatus.OK,
                _page_body(sessions, next_cursor=next_cursor),
            )

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("sync request: " + format, *args)

    return SyncRequestHandler


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}


def run_sync_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: str | None = None,
    *,
    token_file: str | None = None,
    tls_cert_file: str | None = None,
    tls_key_file: str | None = None,
    external_tls_termination: bool = False,
) -> None:
    """Run the secure sync API.

    The token is read from ``token_file``, ``TRACKY_SYNC_TOKEN_FILE``, or
    ``TRACKY_SYNC_TOKEN``; it is never accepted as a CLI value. Without a
    certificate/key pair, ``external_tls_termination`` must be explicitly
    enabled and the listener remains loopback-only.
    """

    selected_token_file = token_file or os.environ.get("TRACKY_SYNC_TOKEN_FILE")
    token = (
        _read_token_file(selected_token_file)
        if selected_token_file
        else _validate_token(os.environ.get("TRACKY_SYNC_TOKEN"))
    )
    if (tls_cert_file is None) != (tls_key_file is None):
        raise ValueError("both TLS certificate and key files are required")
    if tls_cert_file is None and not external_tls_termination:
        raise ValueError("configure TLS certificate/key files or explicit external TLS termination")
    if external_tls_termination and not _is_loopback(host):
        raise ValueError("external TLS termination mode must bind to loopback")

    handler = create_sync_handler(db_path=db_path, auth_token=token)
    server = ThreadingHTTPServer((host, port), handler)
    scheme = "http"
    if tls_cert_file is not None and tls_key_file is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=tls_cert_file, keyfile=tls_key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    logger.info("Tracky Sync API listening on %s://%s:%d", scheme, host, port)

    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.server_close()
        logger.info("Tracky Sync API server stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tracky authenticated Android observation API")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: loopback)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db-path", default=None)
    parser.add_argument(
        "--token-file",
        default=None,
        help="Path to a root/service-readable bearer-token file",
    )
    parser.add_argument("--tls-cert-file", default=None)
    parser.add_argument("--tls-key-file", default=None)
    parser.add_argument(
        "--external-tls-termination",
        action="store_true",
        help="Explicitly allow loopback HTTP behind a trusted TLS terminator",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_sync_server(
        host=args.host,
        port=args.port,
        db_path=args.db_path,
        token_file=args.token_file,
        tls_cert_file=args.tls_cert_file,
        tls_key_file=args.tls_key_file,
        external_tls_termination=args.external_tls_termination,
    )


if __name__ == "__main__":
    main()
