"""Fixture tests for the CS10B decoder and handshake state machine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracky_mcp.protocol import (
    BurstAssembler,
    InfoFrame,
    MeasurementFrame,
    OpaqueBurst,
    ScaleSession,
    SessionState,
    StatusFrame,
    WeightUnit,
    append_checksum,
    build_a0_writes,
    build_over_cmd,
    build_time_push,
    build_time_sync,
    build_unit_config,
    decode_frame,
    has_valid_checksum,
    reassemble_burst,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "cs10b"
FIXTURE_NAMES = ("20260809T182636Z", "20260809T191051Z")


@pytest.fixture(params=FIXTURE_NAMES, ids=lambda name: f"fixture-{name}")
def fixture_dir(request: pytest.FixtureRequest) -> Path:
    return FIXTURE_ROOT / request.param


@pytest.fixture
def session_fixture(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "session.json").read_text(encoding="utf-8"))


@pytest.fixture
def expected_decode(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "expected_decode.json").read_text(encoding="utf-8"))


def _recorded_writes(session_fixture: dict) -> dict[str, bytes]:
    return {
        record["name"]: bytes.fromhex(record["hex"])
        for record in session_fixture["events"]
        if record.get("kind") == "write"
    }


def _recorded_unit_byte(writes: dict[str, bytes]) -> WeightUnit:
    return WeightUnit(writes["unit_config_0x13"][3])


def _recorded_qn_epoch(writes: dict[str, bytes]) -> int:
    time_push = decode_frame(writes["time_push"])
    assert time_push.qn_epoch_seconds is not None
    return time_push.qn_epoch_seconds


def test_weight_golden(expected_decode: dict) -> None:
    decoded = decode_frame(expected_decode["frame_hex"])

    assert isinstance(decoded, MeasurementFrame)
    assert decoded.raw_hex == expected_decode["frame_hex"]
    assert decoded.weight_raw_u16_be == expected_decode["weight_raw_u16_be"]
    assert decoded.weight_formula == expected_decode["weight_formula"]
    assert decoded.weight_kg == expected_decode["weight_kg"]
    assert decoded.word_block == expected_decode["opaque_words"]
    assert decoded.word_provenance.startswith("Opaque five-word block")
    assert decoded.checksum_valid is True


def test_word_block_is_structured_but_opaque(session_fixture: dict) -> None:
    examples = session_fixture["decode_hypotheses"]["opaque_word_block_0x10_examples"]

    for example in examples:
        decoded = decode_frame(example["frame_hex"])
        assert isinstance(decoded, MeasurementFrame)
        assert decoded.b5 == 0x01
        assert decoded.b6 == 0x21
        assert decoded.word_block == example["opaque_words"]
        assert decoded.word_layout is not None


def test_recorded_notifications_decode_and_checksum(session_fixture: dict) -> None:
    notifications = session_fixture["notifications"]
    decoded = [decode_frame(record["hex"]) for record in notifications]

    assert isinstance(decoded[0], InfoFrame)
    assert isinstance(decoded[1], StatusFrame)
    assert decoded[1].opcode == 0x14
    assert isinstance(decoded[2], StatusFrame)
    assert decoded[2].opcode == 0x21
    expected_measurements = sum(record["opcode"] == 0x10 for record in notifications)
    assert sum(isinstance(frame, MeasurementFrame) for frame in decoded) == expected_measurements
    assert all(frame.checksum_valid is True for frame in decoded)
    assert all(has_valid_checksum(bytes.fromhex(record["hex"])) for record in notifications)


def test_known_host_writes_and_time_push_exception(session_fixture: dict) -> None:
    writes = _recorded_writes(session_fixture)
    unit = _recorded_unit_byte(writes)
    qn_epoch_seconds = _recorded_qn_epoch(writes)

    assert build_unit_config(0x20, unit) == writes["unit_config_0x13"]
    assert build_time_push(qn_epoch_seconds) == writes["time_push"]
    assert build_time_sync(0x20, qn_epoch_seconds) == writes["time_sync_0x20"]
    assert build_a0_writes() == [writes["a0_1"], writes["a0_2"]]

    time_push = decode_frame(writes["time_push"])
    assert time_push.checksum_valid is None
    assert time_push.qn_epoch_seconds == qn_epoch_seconds


def test_session_replays_recorded_handshake(session_fixture: dict) -> None:
    writes = _recorded_writes(session_fixture)
    unit = _recorded_unit_byte(writes)
    qn_epoch_seconds = _recorded_qn_epoch(writes)
    session = ScaleSession(unit_byte=unit, qn_epoch_seconds=qn_epoch_seconds)
    notifications = session_fixture["notifications"]
    outputs = [session.feed(record["hex"]) for record in notifications]

    assert outputs[0].tx_writes == [
        writes["unit_config_0x13"],
        writes["time_push"],
    ]
    assert outputs[1].tx_writes == [writes["time_sync_0x20"]]
    assert outputs[2].tx_writes == [writes["a0_1"], writes["a0_2"]]
    expected_ack = build_over_cmd(session.protocol_type or 0x20, 0x10, b6=0x21)
    for output, record in zip(outputs[3:], notifications[3:]):
        frame = decode_frame(record["hex"])
        if isinstance(frame, MeasurementFrame) and frame.b5 == 0x01 and frame.b6 == 0x21:
            assert output.tx_writes == [expected_ack]
        else:
            assert not output.tx_writes
    assert outputs[0].state is SessionState.WAITING_14
    assert outputs[1].state is SessionState.WAITING_21
    assert outputs[2].state is SessionState.LIVE
    assert session.state is SessionState.LIVE
    assert len(session.measurements) == sum(record["opcode"] == 0x10 for record in notifications)
    assert len(session.received_events) == len(notifications)


def test_bad_checksum_is_reported_without_advancing_session(expected_decode: dict) -> None:
    frame = bytearray.fromhex(expected_decode["frame_hex"])
    frame[-1] ^= 0x01
    session = ScaleSession()

    output = session.feed(bytes(frame))

    assert output.events[0].checksum_valid is False
    assert output.tx_writes == []
    assert session.state is SessionState.WAITING_INFO


def test_build_over_cmd() -> None:
    # 6-byte acknowledgment with b6=0x21
    cmd = build_over_cmd(0x20, 0x10, b6=0x21)
    assert cmd == bytes.fromhex("1f0620102176")
    assert has_valid_checksum(cmd)

    # 5-byte legacy acknowledgment with b6=None
    cmd_legacy = build_over_cmd(0x20, 0x10, b6=None)
    assert cmd_legacy == bytes.fromhex("1f05201054")
    assert has_valid_checksum(cmd_legacy)


def test_packet2_decode_and_burst_reassembly() -> None:
    # Packet 1: weight 78.90 kg (0x1ed2), b5=0x01, b6=0x21
    # First opaque block: [4549, 4215, 2190, 2039, 133].
    p1_bytes = append_checksum(
        bytes(
            (
                0x10, 0x12, 0x20, 0x1E, 0xD2, 0x01, 0x21,
                0x11, 0xC5, 0x10, 0x77, 0x08, 0x8E, 0x07, 0xF7, 0x00, 0x85,
            )
        )
    )
    p1 = decode_frame(p1_bytes)
    assert isinstance(p1, MeasurementFrame)
    assert p1.b6 == 0x21
    assert p1.word_block == [4549, 4215, 2190, 2039, 133]
    assert "packet 1/2" in (p1.word_layout or "")

    # Packet 2: weight 78.90 kg (0x1ed2), b5=0x01, b6=0x22
    # Second opaque block: [116, 140, 122, 230, 200].
    p2_bytes = append_checksum(
        bytes(
            (
                0x10, 0x12, 0x20, 0x1E, 0xD2, 0x01, 0x22,
                0x00, 0x74, 0x00, 0x8C, 0x00, 0x7A, 0x00, 0xE6, 0x00, 0xC8,
            )
        )
    )
    p2 = decode_frame(p2_bytes)
    assert isinstance(p2, MeasurementFrame)
    assert p2.b6 == 0x22
    assert p2.word_block == [116, 140, 122, 230, 200]
    assert "packet 2/2" in (p2.word_layout or "")

    burst = reassemble_burst(p1, p2)
    assert isinstance(burst, OpaqueBurst)
    assert burst.block_a == (4549, 4215, 2190, 2039, 133)
    assert burst.block_b == (116, 140, 122, 230, 200)
    assert burst.opaque_words == (
        4549, 4215, 2190, 2039, 133, 116, 140, 122, 230, 200
    )
    assert burst.wire_valid is True
    assert not hasattr(burst, "ohms")
    assert not hasattr(burst, "fluid_ratio")


def test_bad_checksum_cannot_assemble_a_burst() -> None:
    p1 = decode_frame(
        append_checksum(
            bytes((0x10, 0x12, 0x20, 0x1E, 0xD2, 0x01, 0x21, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5))
        )
    )
    p2 = decode_frame(
        append_checksum(
            bytes((0x10, 0x12, 0x20, 0x1E, 0xD2, 0x01, 0x22, 0, 6, 0, 7, 0, 8, 0, 9, 0, 10))
        )
    )
    assert isinstance(p1, MeasurementFrame)
    assert isinstance(p2, MeasurementFrame)
    invalid = bytearray(p1.raw)
    invalid[-1] ^= 1
    invalid_frame = decode_frame(invalid)
    assembler = BurstAssembler()
    assert isinstance(invalid_frame, MeasurementFrame)
    assert assembler.add(invalid_frame) is None
    assert assembler.add(p2) is None
    assert assembler.completed == []


def test_session_burst_flow() -> None:
    session = ScaleSession(qn_epoch_seconds=100)
    info = append_checksum(bytes((0x12, 0x04, 0x20, 0x00)))
    status14 = append_checksum(bytes((0x14, 0x04, 0x20, 0x00)))
    status21 = append_checksum(bytes((0x21, 0x04, 0x20, 0x00)))

    session.feed(info)
    session.feed(status14)
    session.feed(status21)
    assert session.state is SessionState.LIVE

    p1_bytes = append_checksum(
        bytes(
            (
                0x10, 0x12, 0x20, 0x1E, 0xD2, 0x01, 0x21,
                0x11, 0xC5, 0x10, 0x77, 0x08, 0x8E, 0x07, 0xF7, 0x00, 0x85,
            )
        )
    )
    out1 = session.feed(p1_bytes)
    assert len(out1.tx_writes) == 1
    assert out1.tx_writes[0] == build_over_cmd(0x20, 0x10, b6=0x21)
    assert len(session.bursts) == 0

    p2_bytes = append_checksum(
        bytes(
            (
                0x10, 0x12, 0x20, 0x1E, 0xD2, 0x01, 0x22,
                0x00, 0x74, 0x00, 0x8C, 0x00, 0x7A, 0x00, 0xE6, 0x00, 0xC8,
            )
        )
    )
    out2 = session.feed(p2_bytes)
    assert len(out2.tx_writes) == 0
    assert len(session.bursts) == 1
    assert session.bursts[0].block_a == (4549, 4215, 2190, 2039, 133)
    assert session.bursts[0].block_b == (116, 140, 122, 230, 200)

