"""Opaque local device registry tests with injected discovery."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from tracky_mcp.acquisition import DeviceService
from tracky_mcp.storage import DeviceNotFoundError, SQLiteMeasurementStore

NOW = datetime(2026, 8, 11, 17, 0, tzinfo=timezone.utc)
ADDRESS = "AA:BB:CC:DD:EE:FF"


@dataclass
class FakeDevice:
    address: str | None
    name: str | None
    metadata: dict[str, Any]


class FakeScanner:
    def __init__(self, devices: list[FakeDevice]) -> None:
        self.devices = devices
        self.timeouts: list[float] = []

    async def __call__(self, timeout: float) -> list[FakeDevice]:
        self.timeouts.append(timeout)
        return self.devices


def test_discovery_mints_stable_agent_safe_id_and_hides_connection_target(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scanner = FakeScanner(
            [
                FakeDevice(
                    ADDRESS,
                    "QN-Scale",
                    {
                        "service_uuids": ["0000FFE0-0000-1000-8000-00805F9B34FB"],
                        "rssi": -52,
                    },
                ),
                FakeDevice(None, "unconnectable", {}),
            ]
        )
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            service = DeviceService(store, scanner=scanner, clock=lambda: NOW)
            first = await service.discover(timeout=2.5)

            scanner.devices = [FakeDevice(ADDRESS.lower(), "QN-Scale", {"rssi": -48})]
            second = await service.discover(timeout=1.0)
            connection = store.resolve_device(first[0].id)

            assert scanner.timeouts == [2.5, 1.0]
            assert len(first) == len(second) == 1
            assert first[0].id == second[0].id
            assert first[0].address_hash == hashlib.sha256(
                b"AABBCCDDEEFF"
            ).hexdigest()[:12]
            assert not hasattr(first[0], "connection_target")
            assert ADDRESS not in repr(first[0])
            assert ADDRESS.lower() not in repr(connection)
            assert connection.target == ADDRESS.lower()
            assert second[0].metadata == {"rssi": -48}
            assert second[0].advertised_service_uuids == (
                "0000ffe0-0000-1000-8000-00805f9b34fb",
            )
            assert second[0].first_seen_at == NOW
            assert second[0].last_seen_at == NOW

    asyncio.run(scenario())


def test_service_metadata_and_configuration_flow_into_weigh_in_request(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scanner = FakeScanner(
            [
                FakeDevice(
                    ADDRESS,
                    "QN-Scale",
                    {
                        "service_uuids": [
                            "0000fff0-0000-1000-8000-00805f9b34fb",
                            "0000FFE0-0000-1000-8000-00805F9B34FB",
                        ]
                    },
                )
            ]
        )
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            service = DeviceService(store, scanner=scanner, clock=lambda: NOW)
            [device] = await service.discover()
            configured = service.configure(
                device.id,
                alias="bathroom-scale",
                model_label="TR-CS10B",
            )
            request = service.weigh_in_request(
                configured.id,
                condition="barefoot_with_handle",
                timeout_seconds=45,
                metadata={"initiator": "agent"},
            )

            assert configured.advertised_service_uuids == (
                "0000ffe0-0000-1000-8000-00805f9b34fb",
                "0000fff0-0000-1000-8000-00805f9b34fb",
            )
            assert request.device == ADDRESS
            assert request.device_alias == "bathroom-scale"
            assert request.model_label == "TR-CS10B"
            assert request.address_hash == configured.address_hash
            assert request.condition == "barefoot_with_handle"
            assert request.timeout_seconds == 45
            assert request.metadata == {"initiator": "agent"}
            assert service.list_known() == [configured]

    asyncio.run(scenario())


def test_last_seen_advances_without_changing_identity(tmp_path: Path) -> None:
    path = tmp_path / "tracky.sqlite3"
    with SQLiteMeasurementStore(path) as store:
        first = store.register_device(ADDRESS, seen_at=NOW, advertised_name="QN-Scale")
        later = store.register_device(
            ADDRESS,
            seen_at=NOW + timedelta(days=1),
            advertised_name="QN-Scale",
        )

    assert later.id == first.id
    assert later.first_seen_at == NOW
    assert later.last_seen_at == NOW + timedelta(days=1)


def test_unknown_device_handle_fails_without_accepting_raw_address(tmp_path: Path) -> None:
    with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
        service = DeviceService(store, scanner=FakeScanner([]), clock=lambda: NOW)
        with pytest.raises(DeviceNotFoundError):
            service.weigh_in_request(ADDRESS)


def test_discovery_requires_positive_timeout_and_aware_clock(tmp_path: Path) -> None:
    async def scenario() -> None:
        scanner = FakeScanner([FakeDevice(ADDRESS, "QN-Scale", {})])
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            service = DeviceService(
                store,
                scanner=scanner,
                clock=lambda: datetime(2026, 8, 11),
            )
            with pytest.raises(ValueError, match="greater than zero"):
                await service.discover(timeout=0)
            with pytest.raises(ValueError, match="timezone-aware"):
                await service.discover()

    asyncio.run(scenario())
