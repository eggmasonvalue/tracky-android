"""Unit tests for the 24/7 background acquisition daemon."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from tracky_mcp.daemon import TrackyDaemon
from tracky_mcp.storage import SQLiteMeasurementStore


@dataclass
class FakeBleDevice:
    address: str
    name: str | None = None


class FakeScanner:
    def __init__(self, detection_callback: Any, adapter: str | None = None) -> None:
        self.callback = detection_callback
        self.adapter = adapter
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def emit_advertisement(
        self,
        device: FakeBleDevice,
        service_uuids: list[str] | None = None,
    ) -> None:
        adv = SimpleNamespace(service_uuids=service_uuids or [])
        self.callback(device, adv)


class FakeClient:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False

    async def events(self) -> Any:
        yield SimpleNamespace(raw=b"test", opcode=0x12, checksum_valid=True)
        # Yield and then complete
        await asyncio.sleep(0.01)

    async def disconnect(self) -> None:
        self.disconnected = True


def test_daemon_uses_active_bleak_discovery_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    captured: dict[str, Any] = {}

    class ConfiguredScanner:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    bleak = ModuleType("bleak")
    bleak.BleakScanner = ConfiguredScanner  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "bleak", bleak)

    store = SQLiteMeasurementStore(path=tmp_path / "test.db")
    try:
        daemon = TrackyDaemon(store=store, adapter="hci0")
        daemon._create_scanner()
    finally:
        store.close()

    assert captured["scanning_mode"] == "active"
    assert captured["adapter"] == "hci0"
    assert callable(captured["detection_callback"])


def test_daemon_ignores_non_scale_devices(tmp_path: Any) -> None:
    store = SQLiteMeasurementStore(path=tmp_path / "test.db")
    scanner: FakeScanner | None = None

    def fake_scanner_factory(detection_callback: Any, adapter: str | None = None) -> FakeScanner:
        nonlocal scanner
        scanner = FakeScanner(detection_callback, adapter)
        return scanner

    daemon = TrackyDaemon(
        store=store,
        scanner_factory=fake_scanner_factory,
        client_factory=lambda req, obs: FakeClient(),
    )

    async def run() -> None:
        await daemon.start()
        assert scanner is not None and scanner.started

        # Emit non-scale device
        non_scale = FakeBleDevice("11:22:33:44:55:66", name="Headphones")
        scanner.emit_advertisement(non_scale)
        await asyncio.sleep(0.05)

        assert daemon._active_operation_id is None
        assert len(store.list_devices()) == 0

        await daemon.stop()
        assert scanner.stopped

    asyncio.run(run())


def test_daemon_triggers_acquisition_on_scale_seen(tmp_path: Any) -> None:
    store = SQLiteMeasurementStore(path=tmp_path / "test.db")
    scanner: FakeScanner | None = None

    def fake_scanner_factory(detection_callback: Any, adapter: str | None = None) -> FakeScanner:
        nonlocal scanner
        scanner = FakeScanner(detection_callback, adapter)
        return scanner

    daemon = TrackyDaemon(
        store=store,
        scanner_factory=fake_scanner_factory,
        client_factory=lambda req, obs: FakeClient(),
        cooldown_seconds=1.0,
    )

    async def run() -> None:
        await daemon.start()
        scale = FakeBleDevice("AA:BB:CC:DD:EE:FF", name="QN-Scale")
        scanner.emit_advertisement(scale, service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"])

        # Give the async task time to run through acquisition
        await asyncio.sleep(0.1)

        # Device should be registered
        devices = store.list_devices()
        assert len(devices) == 1
        assert devices[0].advertised_name == "QN-Scale"

        await daemon.stop()

    asyncio.run(run())


def test_daemon_cooldown_and_debounce(tmp_path: Any) -> None:
    store = SQLiteMeasurementStore(path=tmp_path / "test.db")
    scanner: FakeScanner | None = None

    def fake_scanner_factory(detection_callback: Any, adapter: str | None = None) -> FakeScanner:
        nonlocal scanner
        scanner = FakeScanner(detection_callback, adapter)
        return scanner

    daemon = TrackyDaemon(
        store=store,
        scanner_factory=fake_scanner_factory,
        client_factory=lambda req, obs: FakeClient(),
        cooldown_seconds=5.0,
    )

    async def run() -> None:
        await daemon.start()
        scale = FakeBleDevice("AA:BB:CC:DD:EE:FF", name="QN-Scale")

        # First advertisement triggers acquisition
        scanner.emit_advertisement(scale)
        await asyncio.sleep(0.05)

        # Immediate second advertisement is ignored due to active or cooldown
        scanner.emit_advertisement(scale)
        await asyncio.sleep(0.1)

        # Only one operation created
        assert daemon._last_completed_at is not None

        await daemon.stop()

    asyncio.run(run())
