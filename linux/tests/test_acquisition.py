"""Persisted acquisition operation tests with no BLE adapter required."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tracky_mcp.acquisition import AcquisitionService, WeighInRequest
from tracky_mcp.ble import FFF1_NOTIFY_UUID, FFF2_WRITE_UUID, WireEvent, WireObserver
from tracky_mcp.protocol import (
    DecodedFrame,
    MeasurementQuality,
    build_unit_config,
    decode_frame,
)
from tracky_mcp.storage import OperationStatus, SessionStatus, SQLiteMeasurementStore

NOW = datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc)
INFO = bytes.fromhex("121220d1e0460003ff07930840060503002d")
MEASUREMENT = bytes.fromhex("1012201ed2012111c51077088e07f70085ca")


class FixedClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        self.value += timedelta(milliseconds=1)
        return self.value


class BlockingWireClient:
    def __init__(self, observer: WireObserver, *, fail: bool = False) -> None:
        self.observer = observer
        self.fail = fail
        self.ready = asyncio.Event()
        self.block = asyncio.Event()
        self.disconnect_calls = 0

    async def events(self) -> AsyncIterator[DecodedFrame]:
        self.observer(WireEvent(NOW + timedelta(milliseconds=10), "rx", FFF1_NOTIFY_UUID, INFO))
        yield decode_frame(INFO)
        self.observer(
            WireEvent(
                NOW + timedelta(milliseconds=11),
                "tx",
                FFF2_WRITE_UUID,
                build_unit_config(),
            )
        )
        self.observer(
            WireEvent(
                NOW + timedelta(milliseconds=12),
                "rx",
                FFF1_NOTIFY_UUID,
                MEASUREMENT,
            )
        )
        self.ready.set()
        yield decode_frame(MEASUREMENT)
        if self.fail:
            raise RuntimeError("simulated link failure")
        await self.block.wait()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


class CapturingFactory:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.client: BlockingWireClient | None = None

    def __call__(
        self,
        _request: WeighInRequest,
        observer: WireObserver,
    ) -> BlockingWireClient:
        self.client = BlockingWireClient(observer, fail=self.fail)
        return self.client


class StableFixtureClient:
    def __init__(self, observer: WireObserver, frames: list[bytes]) -> None:
        self.observer = observer
        self.frames = frames
        self.disconnect_calls = 0

    async def events(self) -> AsyncIterator[DecodedFrame]:
        for index, raw in enumerate(self.frames):
            self.observer(
                WireEvent(
                    NOW + timedelta(milliseconds=index),
                    "rx",
                    FFF1_NOTIFY_UUID,
                    raw,
                )
            )
            yield decode_frame(raw)
            if len(raw) == 18 and raw[5:7] == bytes((0x01, 0x21)):
                self.observer(
                    WireEvent(
                        NOW + timedelta(milliseconds=index, microseconds=100),
                        "tx",
                        FFF2_WRITE_UUID,
                        bytes.fromhex("1f0620102176"),
                    )
                )
        await asyncio.Event().wait()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


async def _wait_until_ready(factory: CapturingFactory) -> BlockingWireClient:
    while factory.client is None:
        await asyncio.sleep(0)
    await factory.client.ready.wait()
    return factory.client


def test_stop_completes_session_without_claiming_a_selected_frame(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = CapturingFactory()
        clock = FixedClock()
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            service = AcquisitionService(store, client_factory=factory, clock=clock)
            operation_id = service.start(
                WeighInRequest(
                    device=object(),
                    device_alias="cs10b-01",
                    model_label="TR-CS10B",
                    address_hash="000000000000",
                    metadata={"initiator": "test"},
                )
            )
            client = await _wait_until_ready(factory)

            running = service.get(operation_id)
            assert running.status is OperationStatus.RUNNING
            assert running.session_id is not None

            completed = await service.stop(operation_id)
            session = service.get_session(operation_id)

            assert completed.status is OperationStatus.COMPLETE
            assert completed.terminal is True
            assert completed.metadata == {"initiator": "test"}
            assert session is not None
            assert session.status is SessionStatus.COMPLETE
            assert session.selected_frame_sequence is None
            assert [frame.direction for frame in session.frames] == ["rx", "tx", "rx"]
            assert [frame.raw for frame in session.frames] == [
                INFO,
                build_unit_config(),
                MEASUREMENT,
            ]
            elapsed = [frame.elapsed_ms for frame in session.frames]
            assert elapsed == sorted(elapsed)
            assert elapsed[1:] == [elapsed[0] + 1, elapsed[0] + 2]
            assert len(session.measurements) == 1
            assert client.disconnect_calls >= 1

    asyncio.run(scenario())


def test_cancel_aborts_session_but_retains_wire_evidence(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = CapturingFactory()
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            service = AcquisitionService(store, client_factory=factory, clock=FixedClock())
            operation_id = service.start(WeighInRequest(device=object()))
            await _wait_until_ready(factory)

            cancelled = await service.cancel(operation_id)
            session = service.get_session(operation_id)

            assert cancelled.status is OperationStatus.CANCELLED
            assert cancelled.error_code == "cancelled"
            assert session is not None
            assert session.status is SessionStatus.ABORTED
            assert len(session.frames) == 3

    asyncio.run(scenario())


def test_transport_failure_is_persisted_instead_of_escaping_background_task(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        factory = CapturingFactory(fail=True)
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            service = AcquisitionService(store, client_factory=factory, clock=FixedClock())
            operation_id = service.start(WeighInRequest(device=object()))

            failed = await service.wait(operation_id)
            session = service.get_session(operation_id)

            assert failed.status is OperationStatus.FAILED
            assert failed.error_code == "acquisition_failed"
            assert "simulated link failure" in (failed.error_message or "")
            assert session is not None
            assert session.status is SessionStatus.ABORTED
            assert [frame.raw for frame in session.frames][-1] == MEASUREMENT

    asyncio.run(scenario())


def test_safety_timeout_fails_without_discarding_partial_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = CapturingFactory()
        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            service = AcquisitionService(store, client_factory=factory, clock=FixedClock())
            operation_id = service.start(
                WeighInRequest(device=object(), timeout_seconds=0.01)
            )

            failed = await service.wait(operation_id)
            session = service.get_session(operation_id)

            assert failed.status is OperationStatus.FAILED
            assert failed.error_code == "timeout"
            assert session is not None
            assert session.status is SessionStatus.ABORTED
            assert session.frames

    asyncio.run(scenario())


def test_startup_recovery_fails_orphaned_handles_and_aborts_open_sessions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tracky.sqlite3"
    with SQLiteMeasurementStore(path) as store:
        operation_id = store.create_operation(created_at=NOW)
        session_id = store.create_session(started_at=NOW)
        store.start_operation(operation_id, session_id=session_id, started_at=NOW)

    with SQLiteMeasurementStore(path) as reopened:
        AcquisitionService(reopened, clock=FixedClock())
        operation = reopened.get_operation(operation_id)
        session = reopened.get_session(session_id)

    assert operation.status is OperationStatus.FAILED
    assert operation.error_code == "process_restarted"
    assert session.status is SessionStatus.ABORTED


def test_operation_handle_survives_store_reopen(tmp_path: Path) -> None:
    path = tmp_path / "tracky.sqlite3"
    with SQLiteMeasurementStore(path) as store:
        operation_id = store.create_operation(
            operation_id="opaque-operation",
            created_at=NOW,
            metadata={"scope": "weigh_in"},
        )
        store.cancel_operation(operation_id, finished_at=NOW + timedelta(seconds=1))

    with SQLiteMeasurementStore(path) as reopened:
        operation = reopened.get_operation(operation_id)

    assert operation.id == "opaque-operation"
    assert operation.kind == "weigh_in"
    assert operation.status is OperationStatus.CANCELLED
    assert operation.metadata == {"scope": "weigh_in"}


def test_stable_fixture_completes_before_safety_timeout_and_persists_quality(
    tmp_path: Path,
) -> None:
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "cs10b"
        / "conditions"
        / "handle_contact_complete.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    frames = [bytes.fromhex(raw) for raw in fixture["notifications"]]

    async def scenario() -> None:
        factory_client: StableFixtureClient | None = None

        def factory(_request: WeighInRequest, observer: WireObserver) -> StableFixtureClient:
            nonlocal factory_client
            factory_client = StableFixtureClient(observer, frames)
            return factory_client

        with SQLiteMeasurementStore(tmp_path / "tracky.sqlite3") as store:
            service = AcquisitionService(store, client_factory=factory, clock=FixedClock())
            operation_id = service.start(
                WeighInRequest(
                    device=object(),
                    timeout_seconds=0.5,
                    completion_idle_seconds=0.01,
                    stable_measurements=3,
                )
            )
            operation = await service.wait(operation_id)
            session = service.get_session(operation_id)

        assert factory_client is not None
        assert operation.status is OperationStatus.COMPLETE
        assert session is not None
        assert session.status is SessionStatus.COMPLETE
        assert session.quality is MeasurementQuality.ACCEPTED
        assert session.quality_reason == "stable_complete_word_burst"
        assert session.completion_reason == "stable_complete_word_burst"
        assert session.selected_frame_sequence is not None
        assert session.selection_policy_version == 1
        assert session.selected_frame is not None
        assert session.selected_frame.measurement is not None
        assert session.selected_frame.measurement.weight_raw_u16_be == 5000
        # All packet-2 frames were consumed before the configured idle grace
        # ended capture; a burst decision did not bypass that grace period.
        assert len(session.frames) == len(frames) + 3
        assert factory_client.disconnect_calls >= 1

    asyncio.run(scenario())
