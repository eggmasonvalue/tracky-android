"""24/7 background acquisition daemon for Linux BlueZ.

Listens for QN-Scale advertisements, triggers the handshake on detection,
records all raw frames into SQLite, and resumes listening for the next weigh-in.
Zero profile knowledge: pure raw telemetry acquisition.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from tracky_mcp.acquisition.service import AcquisitionService, WeighInRequest
from tracky_mcp.ble import ScaleClient, is_scale_device
from tracky_mcp.storage import SQLiteMeasurementStore

logger = logging.getLogger("tracky.daemon")


def _field(source: Any, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


class TrackyDaemon:
    """Unattended BLE listener for zero-touch weigh-in capture."""

    def __init__(
        self,
        store: SQLiteMeasurementStore | None = None,
        *,
        scanner_factory: Callable[..., Any] | None = None,
        client_factory: Callable[..., Any] | None = None,
        cooldown_seconds: float = 10.0,
        acquisition_timeout_seconds: float = 45.0,
        adapter: str | None = None,
    ) -> None:
        self.store = store or SQLiteMeasurementStore()
        self._scanner_factory = scanner_factory
        self._client_factory = client_factory
        self.cooldown_seconds = cooldown_seconds
        self.acquisition_timeout_seconds = acquisition_timeout_seconds
        self.adapter = adapter

        self.service = AcquisitionService(
            store=self.store,
            client_factory=client_factory or self._default_client_factory,
        )
        self._scanner: Any = None
        self._running = False
        self._active_operation_id: str | None = None
        self._active_task: asyncio.Task[Any] | None = None
        self._last_completed_at: datetime | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _default_client_factory(request: WeighInRequest, observer: Any) -> ScaleClient:
        return ScaleClient(
            request.device,
            wire_observer=observer,
            unit=request.unit,
        )

    def _create_scanner(self) -> Any:
        if self._scanner_factory is not None:
            return self._scanner_factory(
                detection_callback=self._on_detection,
                adapter=self.adapter,
            )
        from bleak import BleakScanner

        # BlueZ passive discovery requires kernel ``or_patterns`` support that
        # is absent on common adapters.  Active discovery is the tested
        # configuration and still lets the callback filter by name/service.
        kwargs: dict[str, Any] = {
            "detection_callback": self._on_detection,
            "scanning_mode": "active",
        }
        if self.adapter:
            kwargs["adapter"] = self.adapter
        return BleakScanner(**kwargs)

    def _on_detection(self, device: Any, advertisement_data: Any) -> None:
        """Invoked synchronously by bleak when an advertisement is received."""
        if not self._running:
            return
        if not is_scale_device(device, advertisement_data):
            return

        address = _field(device, "address") or "unknown"
        name = _field(device, "name") or "QN-Scale"

        loop = asyncio.get_running_loop()
        loop.create_task(self._handle_scale_seen(device, advertisement_data, address, name))

    async def _handle_scale_seen(
        self,
        device: Any,
        advertisement_data: Any,
        address: str,
        name: str,
    ) -> None:
        async with self._lock:
            if self._active_operation_id is not None:
                logger.debug("Scale seen but acquisition already active; ignoring")
                return

            now = datetime.now(timezone.utc)
            if self._last_completed_at is not None:
                elapsed = (now - self._last_completed_at).total_seconds()
                if elapsed < self.cooldown_seconds:
                    logger.debug(
                        "Scale seen during cooldown (%0.1fs); ignoring",
                        elapsed,
                    )
                    return

            logger.info("Scale detected: %s. Starting acquisition.", name)

            # Register/update device in store
            service_uuids = _field(advertisement_data, "service_uuids") or []
            known = self.store.register_device(
                connection_target=str(address),
                seen_at=now,
                advertised_name=name,
                advertised_service_uuids=service_uuids,
            )

            request = WeighInRequest(
                device=device,
                unit="kg",
                device_alias=known.alias,
                model_label=known.model_label,
                address_hash=known.address_hash,
                timeout_seconds=self.acquisition_timeout_seconds,
            )

            try:
                operation_id = self.service.start(request)
                self._active_operation_id = operation_id
                self._active_task = asyncio.current_task()
            except Exception as exc:
                logger.exception("Failed to start scale acquisition: %s", exc)
                return

        # Await completion outside the lock so other detection callbacks can check active state
        try:
            operation = await self.service.wait(operation_id)
            logger.info(
                "Acquisition %s finished with status: %s",
                operation_id,
                operation.status.value,
            )
        except Exception as exc:
            logger.exception("Error during acquisition %s: %s", operation_id, exc)
        finally:
            async with self._lock:
                self._active_operation_id = None
                self._active_task = None
                self._last_completed_at = datetime.now(timezone.utc)

    async def start(self) -> None:
        """Start listening for scale advertisements."""
        if self._running:
            return
        logger.info("Starting Tracky 24/7 background acquisition daemon...")
        self._running = True
        self._scanner = self._create_scanner()
        await self._scanner.start()
        logger.info("Scanner active. Waiting for QN-Scale weigh-ins.")

    async def stop(self) -> None:
        """Stop listening and cleanly cancel any active acquisition."""
        if not self._running:
            return
        logger.info("Stopping Tracky daemon...")
        self._running = False
        if self._scanner is not None:
            try:
                await self._scanner.stop()
            except Exception:
                pass
            self._scanner = None

        async with self._lock:
            if self._active_operation_id is not None:
                logger.info("Cancelling in-flight acquisition %s", self._active_operation_id)
                try:
                    await self.service.cancel(self._active_operation_id)
                except Exception:
                    pass
                self._active_operation_id = None

        self.store.close()
        logger.info("Tracky daemon stopped cleanly.")

    async def run_forever(self) -> None:
        """Run until cancelled via asyncio cancellation or signal."""
        await self.start()
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            logger.info("Shutdown signal received")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows event loop doesn't support add_signal_handler
                pass

        try:
            await stop_event.wait()
        finally:
            await self.stop()


def main() -> None:
    """CLI entrypoint for tracky-daemon."""
    parser = argparse.ArgumentParser(
        description="Tracky 24/7 BlueZ background acquisition daemon for CS10B scales"
    )
    parser.add_argument(
        "--db-path",
        help="Path to SQLite database file (default: XDG standard data dir)",
        default=None,
    )
    parser.add_argument(
        "--adapter",
        help="Bluetooth adapter name (e.g. hci0)",
        default=None,
    )
    parser.add_argument(
        "--timeout",
        help="Max weigh-in acquisition duration in seconds (default: 45)",
        type=float,
        default=45.0,
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    store = SQLiteMeasurementStore(path=args.db_path)
    daemon = TrackyDaemon(
        store=store,
        acquisition_timeout_seconds=args.timeout,
        adapter=args.adapter,
    )

    try:
        asyncio.run(daemon.run_forever())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
