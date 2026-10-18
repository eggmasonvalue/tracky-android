"""Persisted, explicit-handle acquisition orchestration.

The service bridges an injected BLE event source to storage and delegates
completion/quality decisions to the versioned protocol policy. MCP can project
these operations later;
this module has no MCP dependency and never treats a connection as state.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from tracky_mcp.ble import ScaleClient, WireEvent, WireObserver
from tracky_mcp.protocol import (
    AcquisitionCompletionPolicy,
    CompletionDecision,
    DecodedFrame,
    MeasurementQuality,
)
from tracky_mcp.storage import (
    AcquisitionOperation,
    MeasurementSession,
    OperationStatus,
    SessionStatus,
    SQLiteMeasurementStore,
)

Clock = Callable[[], datetime]


class AcquisitionClient(Protocol):
    """Transport seam required by :class:`AcquisitionService`."""

    def events(self) -> AsyncIterator[DecodedFrame]:
        """Yield decoded RX events while the transport is active."""

    async def disconnect(self) -> None:
        """Release the transport, tolerating repeated calls."""


@dataclass(frozen=True, slots=True)
class WeighInRequest:
    """Inputs known before starting a local weigh-in acquisition."""

    device: Any = field(repr=False, compare=False)
    unit: str = "kg"
    display_timezone: str = "Asia/Kolkata"
    device_alias: str | None = None
    model_label: str | None = None
    address_hash: str | None = None
    condition: str | None = None
    timeout_seconds: float = 60.0
    completion_idle_seconds: float = 3.0
    stable_measurements: int = 3
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.completion_idle_seconds <= 0:
            raise ValueError("completion_idle_seconds must be greater than zero")
        if self.stable_measurements < 2:
            raise ValueError("stable_measurements must be at least 2")


ClientFactory = Callable[[WeighInRequest, WireObserver], AcquisitionClient]


class OperationNotActiveError(RuntimeError):
    """Raised when this process cannot control a nonterminal operation handle."""


class AcquisitionService:
    """Run and persist weigh-ins behind opaque, pollable operation handles.

    ``start`` returns immediately. The caller may poll ``get``, explicitly
    ``stop`` a successful observation window, or ``cancel`` it. A stream end or
    evidence-backed idle window completes a session. The safety timeout is a
    last-resort failure while preserving every frame received so far.
    """

    def __init__(
        self,
        store: SQLiteMeasurementStore,
        *,
        client_factory: ClientFactory | None = None,
        clock: Clock | None = None,
        recover_on_start: bool = True,
    ) -> None:
        self.store = store
        self._client_factory = client_factory or self._default_client_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        if recover_on_start:
            self.store.recover_interrupted_operations(recovered_at=self._now())

    @staticmethod
    def _default_client_factory(
        request: WeighInRequest,
        observer: WireObserver,
    ) -> AcquisitionClient:
        return ScaleClient(
            request.device,
            unit=request.unit,
            wire_observer=observer,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquisition clock must return a timezone-aware datetime")
        return value

    def start(self, request: WeighInRequest) -> str:
        """Create a persisted operation and schedule its acquisition task."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError("start() requires a running asyncio event loop") from exc

        operation_id = self.store.create_operation(
            created_at=self._now(),
            metadata=request.metadata,
        )
        stop_event = asyncio.Event()
        task = loop.create_task(self._run(operation_id, request, stop_event))
        self._stop_events[operation_id] = stop_event
        self._tasks[operation_id] = task
        task.add_done_callback(
            lambda completed, handle=operation_id: self._task_done(handle, completed)
        )
        return operation_id

    def get(self, operation_id: str) -> AcquisitionOperation:
        """Read status solely from durable storage."""

        return self.store.get_operation(operation_id)

    async def wait(self, operation_id: str) -> AcquisitionOperation:
        """Wait when locally active, otherwise return the persisted status."""

        task = self._tasks.get(operation_id)
        if task is not None:
            await asyncio.shield(task)
        return self.get(operation_id)

    async def stop(self, operation_id: str) -> AcquisitionOperation:
        """End the observation window successfully without selecting a frame."""

        operation = self.get(operation_id)
        if operation.terminal:
            return operation
        stop_event = self._stop_events.get(operation_id)
        task = self._tasks.get(operation_id)
        if stop_event is None or task is None:
            raise OperationNotActiveError(
                f"operation {operation_id} is not controlled by this process"
            )
        stop_event.set()
        await asyncio.shield(task)
        return self.get(operation_id)

    async def cancel(self, operation_id: str) -> AcquisitionOperation:
        """Cancel local work, retaining an aborted session and all evidence."""

        operation = self.get(operation_id)
        if operation.terminal:
            return operation
        task = self._tasks.get(operation_id)
        if task is None:
            raise OperationNotActiveError(
                f"operation {operation_id} is not controlled by this process"
            )
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return self.get(operation_id)

    def _task_done(self, operation_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(operation_id, None)
        self._stop_events.pop(operation_id, None)
        # _run translates every outcome into persisted state. Retrieve the
        # exception to prevent an event-loop warning if an invariant bug escapes.
        if not task.cancelled():
            task.exception()

    async def _run(
        self,
        operation_id: str,
        request: WeighInRequest,
        stop_event: asyncio.Event,
    ) -> None:
        session_id: str | None = None
        client: AcquisitionClient | None = None
        try:
            started_at = self._now()
            session_id = self.store.create_session(
                started_at=started_at,
                display_timezone=request.display_timezone,
                device_alias=request.device_alias,
                model_label=request.model_label,
                address_hash=request.address_hash,
                requested_unit=request.unit,
                condition=request.condition,
                metadata=request.metadata,
            )
            self.store.start_operation(
                operation_id,
                session_id=session_id,
                started_at=started_at,
            )

            policy = AcquisitionCompletionPolicy(
                stable_measurements=request.stable_measurements,
                idle_seconds=request.completion_idle_seconds,
            )

            def record_wire(event: WireEvent) -> None:
                elapsed = max(
                    0,
                    int((event.observed_at - started_at).total_seconds() * 1000),
                )
                self.store.append_frame(
                    session_id,
                    event.data,
                    observed_at=event.observed_at,
                    elapsed_ms=elapsed,
                    direction=event.direction,
                    characteristic_uuid=event.characteristic_uuid,
                )
                # Quality may rely on a TX ACK, but only after that exact wire
                # event has been durably appended to the canonical store.
                policy.observe_wire(event.direction, event.data)

            client = self._client_factory(request, record_wire)
            async with asyncio.timeout(request.timeout_seconds):
                decision = await self._consume_until_stopped(client, stop_event, policy)

            finished_at = self._now()
            selected_frame_sequence = self._selected_frame_sequence(
                session_id,
                decision,
            )
            self.store.finish_acquisition(
                operation_id,
                session_id=session_id,
                status=OperationStatus.COMPLETE,
                finished_at=finished_at,
                quality=decision.quality,
                quality_reason=decision.reason,
                completion_reason=decision.reason,
                selected_frame_sequence=selected_frame_sequence,
                selection_policy_version=(
                    decision.selection_policy_version
                    if selected_frame_sequence is not None
                    else None
                ),
            )
        except asyncio.CancelledError:
            await self._close_failed_session(session_id, operation_id, cancelled=True)
        except TimeoutError:
            await self._close_failed_session(
                session_id,
                operation_id,
                error_code="timeout",
                error_message=(
                    f"Acquisition exceeded the {request.timeout_seconds:g} second safety timeout"
                ),
            )
        except Exception as exc:
            await self._close_failed_session(
                session_id,
                operation_id,
                error_code="acquisition_failed",
                error_message=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    # The primary persisted outcome wins over a teardown race.
                    pass

    def _selected_frame_sequence(
        self,
        session_id: str,
        decision: CompletionDecision,
    ) -> int | None:
        """Resolve the policy's exact selected wire frame after durable capture."""

        if decision.selected_frame_raw is None:
            return None
        session = self.store.get_session(session_id)
        for frame in reversed(session.frames):
            if (
                frame.raw == decision.selected_frame_raw
                and frame.measurement is not None
                and frame.checksum_valid is True
            ):
                return frame.sequence
        # A selection that cannot be tied back to durable evidence is unsafe to
        # project; leave the immutable session unselected rather than guessing.
        return None

    async def _consume_until_stopped(
        self,
        client: AcquisitionClient,
        stop_event: asyncio.Event,
        policy: AcquisitionCompletionPolicy,
    ) -> CompletionDecision:
        iterator = client.events().__aiter__()
        next_event: asyncio.Task[DecodedFrame] | None = None
        stopped: asyncio.Task[bool] | None = None
        idle: asyncio.Task[None] | None = None
        try:
            while True:
                next_event = asyncio.create_task(anext(iterator))
                stopped = asyncio.create_task(stop_event.wait())
                wait_for: set[asyncio.Task[Any]] = {next_event, stopped}
                if policy.can_finish_after_idle:
                    idle = asyncio.create_task(asyncio.sleep(policy.idle_seconds))
                    wait_for.add(idle)
                done, pending = await asyncio.wait(
                    wait_for,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                # Prefer an event delivered concurrently with stop/idle so a
                # packet-2 response is not mistaken for an idle boundary.
                if next_event in done:
                    try:
                        event = next_event.result()
                    except StopAsyncIteration:
                        return policy.finish("stream_closed")
                    policy.observe(event)
                    next_event = None
                    stopped = None
                    idle = None
                    continue
                if stopped in done and stopped.result():
                    return policy.finish("explicit_stop")
                if idle is not None and idle in done:
                    return policy.finish("measurement_idle")
        finally:
            active = [task for task in (next_event, stopped, idle) if task is not None]
            for task in active:
                if not task.done():
                    task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()

    async def _close_failed_session(
        self,
        session_id: str | None,
        operation_id: str,
        *,
        cancelled: bool = False,
        error_code: str = "cancelled",
        error_message: str = "Operation cancelled",
    ) -> None:
        finished_at = self._now()
        operation = self.store.get_operation(operation_id)
        if operation.status not in {OperationStatus.PENDING, OperationStatus.RUNNING}:
            return
        status = OperationStatus.CANCELLED if cancelled else OperationStatus.FAILED
        if session_id is not None and operation.status is OperationStatus.RUNNING:
            self.store.finish_acquisition(
                operation_id,
                session_id=session_id,
                status=status,
                finished_at=finished_at,
                error_code="cancelled" if cancelled else error_code,
                error_message=error_message,
                quality=MeasurementQuality.INDETERMINATE,
                quality_reason=error_code,
                completion_reason=error_code,
            )
            return
        if session_id is not None:
            session = self.store.get_session(session_id)
            if session.status is SessionStatus.OPEN:
                self.store.abort_session(
                    session_id,
                    ended_at=finished_at,
                    quality=MeasurementQuality.INDETERMINATE,
                    quality_reason=error_code,
                    completion_reason=error_code,
                )
        if cancelled:
            self.store.cancel_operation(
                operation_id,
                finished_at=finished_at,
                error_message=error_message,
            )
        else:
            self.store.fail_operation(
                operation_id,
                finished_at=finished_at,
                error_code=error_code,
                error_message=error_message,
            )

    def get_session(self, operation_id: str) -> MeasurementSession | None:
        """Resolve an operation's durable session without connection state."""

        operation = self.get(operation_id)
        if operation.session_id is None:
            return None
        return self.store.get_session(operation.session_id)


__all__ = [
    "AcquisitionClient",
    "AcquisitionService",
    "ClientFactory",
    "Clock",
    "OperationNotActiveError",
    "WeighInRequest",
]
