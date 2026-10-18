"""Mocked BLE transport tests; no adapter or bleak installation is required."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from tracky_mcp.ble import (
    FFF1_NOTIFY_UUID,
    FFF2_WRITE_UUID,
    ScaleClient,
    scan_scales,
)
from tracky_mcp.protocol import (
    MeasurementFrame,
    WeightUnit,
    append_checksum,
    build_time_push,
    build_unit_config,
    decode_frame,
)


@dataclass
class FakeDevice:
    address: str
    name: str | None = None
    metadata: dict[str, Any] | None = None


class FakeScanner:
    calls: list[tuple[float, bool]] = []

    @classmethod
    async def discover(cls, *, timeout: float, return_adv: bool = False) -> dict[str, Any]:
        cls.calls.append((timeout, return_adv))
        return {
            "scale": (
                FakeDevice("AA:BB", name="Other"),
                SimpleNamespace(service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"]),
            ),
            "named": (FakeDevice("CC:DD", name="QN-Scale"), SimpleNamespace()),
            "other": (FakeDevice("EE:FF", name="Other"), SimpleNamespace()),
        }


class FakeClient:
    def __init__(self) -> None:
        self.callback: Any = None
        self.writes: list[tuple[str, bytes]] = []
        self.connected = False
        self.start_calls: list[str] = []
        self.stop_calls: list[str] = []
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self.connected = True

    async def start_notify(self, uuid: str, callback: Any) -> None:
        self.start_calls.append(uuid)
        self.callback = callback

    async def stop_notify(self, uuid: str) -> None:
        self.stop_calls.append(uuid)

    async def write_gatt_char(self, uuid: str, data: bytes) -> None:
        self.writes.append((uuid, data))

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def notify(self, frame: bytes) -> None:
        self.callback(SimpleNamespace(uuid=FFF1_NOTIFY_UUID), bytearray(frame))
        # The real bleak callback is synchronous; give its scheduled write task
        # a turn before the test inspects the wire writes.
        await asyncio.sleep(0)


def _checksummed(*body: int) -> bytes:
    return append_checksum(bytes(body))


INFO = _checksummed(0x12, 0x04, 0x20, 0x00)
STATUS_14 = _checksummed(0x14, 0x04, 0x20, 0x00)
STATUS_21 = _checksummed(0x21, 0x04, 0x20, 0x00)
MEASUREMENT = _checksummed(
    0x10,
    0x11,
    0x20,
    0x1E,
    0xE6,
    0x01,
    0x21,
    0x00,
    0x01,
    0x00,
    0x02,
    0x00,
    0x03,
    0x00,
    0x04,
    0x00,
    0x05,
)


def test_scan_filters_qn_name_and_advertised_service_without_bleak() -> None:
    devices = asyncio.run(scan_scales(2.5, scanner=FakeScanner))

    assert [device.address for device in devices] == ["AA:BB", "CC:DD"]
    assert FakeScanner.calls == [(2.5, True)]


def test_mock_notifications_drive_session_writes_and_measurements() -> None:
    async def scenario() -> None:
        fake = FakeClient()
        observed_wire_events: list[Any] = []
        client = ScaleClient(
            "AA:BB",
            client=fake,
            wire_observer=observed_wire_events.append,
            unit=WeightUnit.LB,
            qn_epoch_seconds=123,
        )

        async with client:
            await client.connect()
            assert fake.start_calls == [FFF1_NOTIFY_UUID]

            for frame in (INFO, STATUS_14, STATUS_21, MEASUREMENT):
                await fake.notify(frame)

            assert [uuid for uuid, _data in fake.writes] == [
                FFF2_WRITE_UUID,
                FFF2_WRITE_UUID,
                FFF2_WRITE_UUID,
                FFF2_WRITE_UUID,
                FFF2_WRITE_UUID,
                FFF2_WRITE_UUID,
            ]
            assert fake.writes[:2] == [
                (FFF2_WRITE_UUID, build_unit_config(0x20, WeightUnit.LB)),
                (FFF2_WRITE_UUID, build_time_push(123)),
            ]
            assert decode_frame(fake.writes[2][1]).opcode == 0x20
            assert decode_frame(fake.writes[5][1]).command_name == "over_0x1f"
            assert len(client.measurements) == 1
            assert client.measurements[0].weight_kg == 79.10
            assert [event.direction for event in client.wire_events] == [
                "rx",
                "tx",
                "tx",
                "rx",
                "tx",
                "rx",
                "tx",
                "tx",
                "rx",
                "tx",
            ]
            assert observed_wire_events == client.wire_events
            assert all(event.observed_at.utcoffset() is not None for event in client.wire_events)
            assert [event.data for event in client.wire_events if event.direction == "rx"] == [
                INFO,
                STATUS_14,
                STATUS_21,
                MEASUREMENT,
            ]

            events = [await client.next_event() for _ in range(4)]
            assert isinstance(events[-1], MeasurementFrame)
            assert client.received_events == events

        assert fake.stop_calls == [FFF1_NOTIFY_UUID]
        assert fake.disconnect_calls == 1

    asyncio.run(scenario())


def test_backend_disconnect_closes_active_event_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tracky_mcp.ble.client as client_module

    created: list[Any] = []

    class CallbackClient(FakeClient):
        def __init__(self, _device: Any, *, disconnected_callback: Any) -> None:
            super().__init__()
            self.disconnected_callback = disconnected_callback
            created.append(self)

        def drop_link(self) -> None:
            self.connected = False
            self.disconnected_callback(self)

    monkeypatch.setattr(client_module, "_load_bleak_client", lambda: CallbackClient)

    async def scenario() -> None:
        client = ScaleClient("AA:BB")
        await client.connect()

        async def consume() -> list[Any]:
            return [event async for event in client.events()]

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        created[0].drop_link()

        assert await consumer == []
        assert client.is_connected is False

    asyncio.run(scenario())


def test_disconnect_ignores_benign_stop_notify_race() -> None:
    class FlakyNotifyClient(FakeClient):
        async def stop_notify(self, uuid: str) -> None:
            self.stop_calls.append(uuid)
            raise RuntimeError("org.bluez.Error.Failed: No notify session started")

    async def scenario() -> None:
        fake = FlakyNotifyClient()
        client = ScaleClient("AA:BB", client=fake)
        await client.connect()
        await client.disconnect()  # must not raise
        assert fake.stop_calls == [FFF1_NOTIFY_UUID]
        assert fake.disconnect_calls == 1

    asyncio.run(scenario())
