"""Thin async BlueZ/bleak transport for the observed CS10B GATT path.

The transport owns only scanning, connection setup, notification delivery, and
writes.  Frame decoding and handshake decisions stay in
:mod:`tracky_mcp.protocol`.

``bleak`` is imported lazily so the rest of the package and mock-based tests do
not need the optional BLE extra installed.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, TypeAlias

from tracky_mcp.protocol import (
    DecodedFrame,
    MeasurementFrame,
    ScaleSession,
    SessionOutput,
    WeightUnit,
)

# Bleak accepts the canonical 128-bit representation for Bluetooth SIG 16-bit
# UUIDs.  Keeping the values here avoids a transport dependency in protocol/.
BLUETOOTH_BASE_UUID = "0000{}-0000-1000-8000-00805f9b34fb"
FFE0_SERVICE_UUID = BLUETOOTH_BASE_UUID.format("ffe0")
FFF0_SERVICE_UUID = BLUETOOTH_BASE_UUID.format("fff0")
FFF1_NOTIFY_UUID = BLUETOOTH_BASE_UUID.format("fff1")
FFF2_WRITE_UUID = BLUETOOTH_BASE_UUID.format("fff2")
ADVERTISED_SERVICE_UUIDS = frozenset({FFE0_SERVICE_UUID, FFF0_SERVICE_UUID})
_ADVERTISED_SERVICE_16 = frozenset({"ffe0", "fff0"})

UnitValue: TypeAlias = int | WeightUnit | str
Clock: TypeAlias = Callable[[], Any]
ClientFactory: TypeAlias = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class WireEvent:
    """One timestamped frame crossing the observed GATT boundary."""

    observed_at: datetime
    direction: Literal["rx", "tx"]
    characteristic_uuid: str
    data: bytes


WireObserver: TypeAlias = Callable[[WireEvent], None]
WireClock: TypeAlias = Callable[[], datetime]


class BleakUnavailableError(ImportError):
    """Raised when the real transport is used without the optional extra."""


class SessionProtocol(Protocol):
    """Small injectable seam implemented by :class:`ScaleSession`."""

    def feed(self, frame: bytes) -> SessionOutput:
        """Decode one notification and return any immediate writes."""


class ScaleDisconnectedError(RuntimeError):
    """Raised when an event consumer waits past an explicit disconnect."""


_CLOSED = object()


class _EventError:
    __slots__ = ("error",)

    def __init__(self, error: Exception) -> None:
        self.error = error


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _load_bleak_client() -> Any:
    try:
        from bleak import BleakClient
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise BleakUnavailableError(
            "BLE transport requires the optional 'ble' dependency; install "
            "with `python -m pip install -e '.[ble]'`."
        ) from exc
    return BleakClient


def _load_bleak_scanner() -> Any:
    try:
        from bleak import BleakScanner
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise BleakUnavailableError(
            "BLE scanning requires the optional 'ble' dependency; install "
            "with `python -m pip install -e '.[ble]'`."
        ) from exc
    return BleakScanner


def _field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _values(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return iter(value)
    except TypeError:
        return (value,)


def _uuid16(value: Any) -> str | None:
    """Return a Bluetooth SIG UUID's 16-bit portion when it is recognizable."""

    text = str(value).strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if len(text) == 4 and all(char in "0123456789abcdef" for char in text):
        return text
    first = text.split("-", 1)[0]
    if len(first) == 8 and first.startswith("0000"):
        short = first[4:]
        if all(char in "0123456789abcdef" for char in short):
            return short
    return None


def _advertised_names(device: Any, advertisement_data: Any) -> Iterable[str]:
    for source in (advertisement_data, device):
        for name in ("local_name", "name"):
            value = _field(source, name)
            if value is not None:
                yield str(value)

        metadata = _field(source, "metadata")
        if metadata is not None:
            for name in ("local_name", "name"):
                value = _field(metadata, name)
                if value is not None:
                    yield str(value)


def _advertised_services(device: Any, advertisement_data: Any) -> Iterable[Any]:
    for source in (advertisement_data, device):
        for name in ("service_uuids", "uuids"):
            yield from _values(_field(source, name))

        metadata = _field(source, "metadata")
        if metadata is not None:
            for name in ("service_uuids", "uuids"):
                yield from _values(_field(metadata, name))


def is_scale_device(device: Any, advertisement_data: Any = None) -> bool:
    """Return whether a discovery result looks like a QN CS10B scale.

    The observed device advertises ``QN-Scale``.  Some BlueZ discovery paths
    expose only service UUIDs, so the FFE0/FFF0 16-bit families are accepted as
    an alternative identifying signal.
    """

    for name in _advertised_names(device, advertisement_data):
        if name.strip().casefold().startswith("qn-scale"):
            return True
    return any(
        _uuid16(service) in _ADVERTISED_SERVICE_16
        for service in _advertised_services(device, advertisement_data)
    )


def _discovery_items(result: Any) -> Iterable[tuple[Any, Any]]:
    if isinstance(result, Mapping):
        values = result.values()
    else:
        values = result

    for item in values:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            yield item[0], item[1]
        else:
            yield item, None


async def _discover(scanner: Any, timeout: float) -> Any:
    discover = getattr(scanner, "discover", None)
    if discover is None and callable(scanner):
        discover = scanner
    if discover is None:
        raise TypeError("scanner must provide an async discover() method")

    kwargs: dict[str, Any] = {"timeout": timeout}
    try:
        parameters = inspect.signature(discover).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "return_adv" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        kwargs["return_adv"] = True
    return await _maybe_await(discover(**kwargs))


async def scan_scales(
    timeout: float = 5.0,
    *,
    scanner: Any = None,
) -> list[Any]:
    """Discover nearby QN-Scale devices using an injectable scanner.

    The returned values are the underlying bleak ``BLEDevice`` objects, so one
    can pass a result directly to :class:`ScaleClient`.  Discovery accepts both
    Bleak's ``return_adv=True`` mapping and simple lists from test doubles.
    """

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    scanner = _load_bleak_scanner() if scanner is None else scanner
    result = await _discover(scanner, timeout)

    devices: list[Any] = []
    seen: set[Any] = set()
    for device, advertisement_data in _discovery_items(result):
        if not is_scale_device(device, advertisement_data):
            continue
        address = _field(device, "address")
        key: Any = ("address", str(address).casefold()) if address else ("object", id(device))
        try:
            already_seen = key in seen
        except TypeError:
            already_seen = False
        if already_seen:
            continue
        try:
            seen.add(key)
        except TypeError:
            pass
        devices.append(device)
    return devices


def _unit_byte(value: UnitValue) -> int | WeightUnit:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"kg", "kilogram", "kilograms"}:
            return WeightUnit.KG
        if normalized in {"lb", "lbs", "pound", "pounds"}:
            return WeightUnit.LB
        try:
            return int(value, 0)
        except ValueError as exc:
            raise ValueError("unit must be kg, lb, or an unsigned unit byte") from exc
    return value


class ScaleClient:
    """Async transport for one CS10B connection.

    A client creates a :class:`~tracky_mcp.protocol.ScaleSession` by default.
    Pass ``session`` to inject a fake or caller-owned protocol seam.  The
    notification callback feeds the session, queues every decoded event, and
    serializes returned writes to FFF2.
    """

    def __init__(
        self,
        device: Any,
        *,
        unit: UnitValue = WeightUnit.KG,
        unit_byte: UnitValue | None = None,
        clock: Clock | None = None,
        qn_epoch_seconds: int | None = None,
        session: SessionProtocol | None = None,
        client: Any = None,
        client_factory: ClientFactory | None = None,
        notify_uuid: str = FFF1_NOTIFY_UUID,
        write_uuid: str = FFF2_WRITE_UUID,
        wire_observer: WireObserver | None = None,
        wire_clock: WireClock | None = None,
    ) -> None:
        if client is not None and client_factory is not None:
            raise TypeError("pass client or client_factory, not both")

        selected_unit = _unit_byte(unit if unit_byte is None else unit_byte)
        self.device = device
        self.notify_uuid = notify_uuid
        self.write_uuid = write_uuid
        self.wire_observer = wire_observer
        self._wire_clock = wire_clock or (lambda: datetime.now(timezone.utc))
        self.session: SessionProtocol = session or ScaleSession(
            unit_byte=selected_unit,
            clock=clock,
            qn_epoch_seconds=qn_epoch_seconds,
        )
        self._client = client
        self._client_factory = client_factory
        self._connected = False
        self._notifications_started = False
        self._has_connected = False
        self._event_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._received_events: list[DecodedFrame] = []
        self._measurements: list[MeasurementFrame] = []
        self._wire_events: list[WireEvent] = []
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self._background_errors: list[Exception] = []
        self._write_lock = asyncio.Lock()
        self._closed_queued = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def received_events(self) -> list[DecodedFrame]:
        return self._received_events

    @property
    def measurements(self) -> list[MeasurementFrame]:
        return self._measurements

    @property
    def wire_events(self) -> list[WireEvent]:
        return self._wire_events

    def _record_wire_event(
        self,
        direction: Literal["rx", "tx"],
        characteristic_uuid: str,
        data: bytes | bytearray | memoryview,
    ) -> WireEvent:
        observed_at = self._wire_clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("wire_clock must return a timezone-aware datetime")
        event = WireEvent(
            observed_at=observed_at,
            direction=direction,
            characteristic_uuid=characteristic_uuid,
            data=bytes(data),
        )
        self._wire_events.append(event)
        if self.wire_observer is not None:
            self.wire_observer(event)
        return event

    def _drain_event_queue(self) -> None:
        while True:
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _prepare_connection(self) -> None:
        if self._has_connected:
            reset = getattr(self.session, "reset", None)
            if callable(reset):
                reset()
            self._received_events.clear()
            self._measurements.clear()
            self._wire_events.clear()
        self._drain_event_queue()
        self._background_errors.clear()
        self._closed_queued = False

    def _queue_closed(self) -> None:
        if not self._closed_queued:
            self._event_queue.put_nowait(_CLOSED)
            self._closed_queued = True

    def _queue_error(self, error: Exception) -> None:
        self._background_errors.append(error)
        if not self._closed_queued:
            self._event_queue.put_nowait(_EventError(error))

    async def connect(self) -> None:
        """Connect and enable notifications on the observed FFF1 UUID."""

        if self._connected:
            return
        self._prepare_connection()

        if self._client is None:
            if self._client_factory is None:
                factory = _load_bleak_client()
                self._client = await _maybe_await(
                    factory(self.device, disconnected_callback=self._disconnected_callback)
                )
            else:
                self._client = await _maybe_await(self._client_factory(self.device))
        client = self._client
        if client is None:
            raise RuntimeError("client factory returned None")

        try:
            await _maybe_await(client.connect())
            # Mark connected before start_notify: a backend/test double may
            # invoke the callback from inside start_notify itself.
            self._connected = True
            await _maybe_await(client.start_notify(self.notify_uuid, self._notification_callback))
            self._notifications_started = True
            self._has_connected = True
        except BaseException:
            self._connected = False
            try:
                if self._notifications_started:
                    await _maybe_await(client.stop_notify(self.notify_uuid))
            finally:
                self._notifications_started = False
                try:
                    await _maybe_await(client.disconnect())
                finally:
                    self._queue_closed()
            raise

    def _disconnected_callback(self, _client: Any) -> None:
        """Translate a peripheral/backend disconnect into event-stream closure."""

        self._connected = False
        self._notifications_started = False
        self._queue_closed()

    async def _wait_for_writes(self) -> list[BaseException]:
        errors: list[BaseException] = []
        while self._pending_tasks:
            tasks = tuple(self._pending_tasks)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    errors.append(result)
            self._pending_tasks.difference_update(tasks)
        return errors

    @staticmethod
    def _is_benign_teardown_error(error: BaseException) -> bool:
        """True for BlueZ races already observed on live disconnect.

        When the peripheral drops notify/link first, ``stop_notify`` can raise
        ``No notify session started``. Treat that as successful teardown rather
        than failing an otherwise clean session.
        """

        text = str(error).casefold()
        markers = (
            "no notify session started",
            "not connected",
            "disconnected",
        )
        return any(marker in text for marker in markers)

    async def disconnect(self) -> None:
        """Stop notifications, finish queued writes, and disconnect cleanly."""

        client = self._client
        if client is None:
            self._connected = False
            self._queue_closed()
            return
        if not (self._connected or self._notifications_started or self._pending_tasks):
            return

        errors: list[BaseException] = []
        try:
            if self._notifications_started:
                stop_notify = getattr(client, "stop_notify", None)
                if stop_notify is not None:
                    try:
                        await _maybe_await(stop_notify(self.notify_uuid))
                    except BaseException as exc:  # clean up before reporting it
                        if not self._is_benign_teardown_error(exc):
                            errors.append(exc)
            self._notifications_started = False
            errors.extend(await self._wait_for_writes())
        finally:
            try:
                await _maybe_await(client.disconnect())
            except BaseException as exc:
                if not self._is_benign_teardown_error(exc):
                    errors.append(exc)
            finally:
                self._connected = False
                self._notifications_started = False
                self._queue_closed()

        if errors:
            raise errors[0]

    def _record_output(self, output: SessionOutput) -> None:
        for event in output.events:
            self._received_events.append(event)
            if isinstance(event, MeasurementFrame):
                self._measurements.append(event)
            if not self._closed_queued:
                self._event_queue.put_nowait(event)

    def _feed_notification(self, data: bytes | bytearray | memoryview) -> SessionOutput:
        self._record_wire_event("rx", self.notify_uuid, data)
        output = self.session.feed(bytes(data))
        self._record_output(output)
        return output

    async def _write_writes(self, writes: Iterable[bytes]) -> None:
        client = self._client
        if client is None:
            raise RuntimeError("cannot write without a BLE client")
        async with self._write_lock:
            for payload in writes:
                payload = bytes(payload)
                await _maybe_await(client.write_gatt_char(self.write_uuid, payload))
                self._record_wire_event("tx", self.write_uuid, payload)

    def _schedule_writes(self, writes: Iterable[bytes]) -> None:
        writes = tuple(writes)
        if not writes:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            self._queue_error(RuntimeError("BLE notification callback needs an asyncio loop"))
            raise exc from None
        task = loop.create_task(self._write_writes(writes))
        self._pending_tasks.add(task)
        task.add_done_callback(self._write_task_done)

    def _write_task_done(self, task: asyncio.Task[Any]) -> None:
        self._pending_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._queue_error(error)

    def _notification_callback(self, _sender: Any, data: bytearray) -> SessionOutput | None:
        """Synchronous callback shape accepted by bleak and test doubles."""

        try:
            output = self._feed_notification(data)
            self._schedule_writes(output.tx_writes)
        except Exception as exc:
            self._queue_error(exc)
            return None
        return output

    async def handle_notification(
        self,
        sender: Any = None,
        data: bytes | bytearray | memoryview | None = None,
    ) -> SessionOutput:
        """Feed one notification directly, useful for deterministic replay/tests.

        It accepts either ``handle_notification(data)`` or bleak's
        ``handle_notification(sender, data)`` shape and awaits all writes
        generated by that notification before returning.
        """

        if data is None:
            data = sender
        if data is None:
            raise TypeError("notification data is required")
        output = self._feed_notification(data)
        await self._write_writes(output.tx_writes)
        return output

    async def next_event(self) -> DecodedFrame:
        """Wait for and return the next decoded event from the notification queue."""

        if not self._connected:
            await self.connect()
        item = await self._event_queue.get()
        if item is _CLOSED:
            raise ScaleDisconnectedError("BLE client disconnected")
        if isinstance(item, _EventError):
            raise item.error
        return item

    async def events(self) -> AsyncIterator[DecodedFrame]:
        """Yield decoded events until the consumer or connection stops.

        The stream auto-connects when needed and disconnects in its ``finally``
        block, making ``async for`` safe to use without a separate context
        manager.  An ``async with ScaleClient(...)`` is also supported.
        """

        if not self._connected:
            await self.connect()
        try:
            while True:
                item = await self._event_queue.get()
                if item is _CLOSED:
                    return
                if isinstance(item, _EventError):
                    raise item.error
                yield item
        finally:
            await self.disconnect()

    async def __aenter__(self) -> ScaleClient:
        await self.connect()
        return self

    async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        await self.disconnect()


__all__ = [
    "ADVERTISED_SERVICE_UUIDS",
    "BLUETOOTH_BASE_UUID",
    "BleakUnavailableError",
    "ClientFactory",
    "Clock",
    "FFE0_SERVICE_UUID",
    "FFF0_SERVICE_UUID",
    "FFF1_NOTIFY_UUID",
    "FFF2_WRITE_UUID",
    "ScaleClient",
    "ScaleDisconnectedError",
    "SessionProtocol",
    "UnitValue",
    "WireClock",
    "WireEvent",
    "WireObserver",
    "is_scale_device",
    "scan_scales",
]
