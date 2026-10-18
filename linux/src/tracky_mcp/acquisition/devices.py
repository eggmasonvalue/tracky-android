"""Local device discovery and opaque-handle resolution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from tracky_mcp.ble import scan_scales
from tracky_mcp.storage import KnownDevice, SQLiteMeasurementStore

from .service import WeighInRequest

Scanner = Callable[[float], Awaitable[list[Any]]]
Clock = Callable[[], datetime]


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _services(device: Any) -> tuple[str, ...]:
    values: list[Any] = []
    for source in (device, _field(device, "metadata")):
        if source is None:
            continue
        for name in ("service_uuids", "uuids"):
            candidate = _field(source, name)
            if candidate is None:
                continue
            if isinstance(candidate, str):
                values.append(candidate)
            else:
                try:
                    values.extend(candidate)
                except TypeError:
                    values.append(candidate)
    return tuple(sorted({str(value).strip().lower() for value in values if str(value).strip()}))


def _safe_metadata(device: Any) -> dict[str, Any]:
    """Keep small scalar observations; never serialize backend objects wholesale."""

    result: dict[str, Any] = {}
    for source in (device, _field(device, "metadata")):
        for name in ("rssi", "tx_power"):
            value = _field(source, name)
            if isinstance(value, (int, float, str, bool)):
                result[name] = value
    return result


class DeviceService:
    """Discover scales and keep connection addresses behind opaque local IDs."""

    def __init__(
        self,
        store: SQLiteMeasurementStore,
        *,
        scanner: Scanner | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self._scanner = scanner or self._default_scanner
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    async def _default_scanner(timeout: float) -> list[Any]:
        return await scan_scales(timeout)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("device clock must return a timezone-aware datetime")
        return value

    async def discover(self, *, timeout: float = 5.0) -> list[KnownDevice]:
        """Scan and upsert scales, returning only agent-safe identities."""

        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        devices = await self._scanner(timeout)
        seen_at = self._now()
        discovered: list[KnownDevice] = []
        for device in devices:
            target = _field(device, "address")
            if target is None or not str(target).strip():
                # A device without a reconnectable target cannot receive a
                # durable handle; omit it rather than minting a broken one.
                continue
            name = _field(device, "name") or _field(_field(device, "metadata"), "local_name")
            discovered.append(
                self.store.register_device(
                    str(target),
                    seen_at=seen_at,
                    advertised_name=None if name is None else str(name),
                    advertised_service_uuids=_services(device),
                    metadata=_safe_metadata(device),
                )
            )
        return discovered

    def list_known(self, *, limit: int = 100) -> list[KnownDevice]:
        return self.store.list_devices(limit=limit)

    def configure(
        self,
        device_id: str,
        *,
        alias: str | None,
        model_label: str | None,
    ) -> KnownDevice:
        current = self.store.get_device(device_id)
        return self.store.configure_device(
            device_id,
            alias=current.alias if alias is None else alias,
            model_label=current.model_label if model_label is None else model_label,
        )

    def weigh_in_request(
        self,
        device_id: str,
        *,
        unit: str = "kg",
        display_timezone: str = "Asia/Kolkata",
        condition: str | None = None,
        timeout_seconds: float = 60.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> WeighInRequest:
        """Resolve a private connection target only for acquisition startup."""

        connection = self.store.resolve_device(device_id)
        device = connection.device
        return WeighInRequest(
            device=connection.target,
            unit=unit,
            display_timezone=display_timezone,
            device_alias=device.alias or device.id,
            model_label=device.model_label,
            address_hash=device.address_hash,
            condition=condition,
            timeout_seconds=timeout_seconds,
            metadata=dict(metadata or {}),
        )


__all__ = ["Clock", "DeviceService", "Scanner"]
