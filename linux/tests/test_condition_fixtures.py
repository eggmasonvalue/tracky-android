"""Sanitized contact-condition and quality-policy fixture tests."""

from __future__ import annotations

import json
from pathlib import Path

from tracky_mcp.protocol import (
    AcquisitionCompletionPolicy,
    MeasurementFrame,
    MeasurementQuality,
    decode_frame,
)

ROOT = Path(__file__).parents[1] / "fixtures" / "cs10b"
GROUNDED = ROOT / "20260809T194335Z"
UNPLUGGED = ROOT / "20260809T194641Z"
CONDITION_ROOT = ROOT / "conditions"
POLICY_FIXTURES = (
    CONDITION_ROOT / "handle_contact_complete.json",
    CONDITION_ROOT / "foot_only_contact_failed.json",
    CONDITION_ROOT / "foot_only_interrupted.json",
)


def _load(dir_path: Path) -> tuple[dict, dict]:
    session = json.loads((dir_path / "session.json").read_text(encoding="utf-8"))
    expected = json.loads((dir_path / "expected_decode.json").read_text(encoding="utf-8"))
    return session, expected


def test_handle_grounded_has_nonzero_opaque_block() -> None:
    session, expected = _load(GROUNDED)
    assert session["condition"] == "feet_handle_usbc_connected_on_ground"
    decoded = decode_frame(expected["frame_hex"])
    assert isinstance(decoded, MeasurementFrame)
    assert decoded.weight_kg == 78.9
    assert decoded.b5 == 0x01 and decoded.b6 == 0x21
    assert decoded.word_block == [4549, 4215, 2190, 2039, 133]
    assert all(value != 0 for value in decoded.word_block)
    assert session["decode_hypotheses"]["opaque_words_nonzero_count"] > 0
    assert session["decode_hypotheses"]["opaque_words_all_zero_count"] == 0


def test_handle_unplugged_zero_opaque_block_still_decodes_weight() -> None:
    session, expected = _load(UNPLUGGED)
    assert session["condition"] == "feet_handle_usbc_unplugged"
    decoded = decode_frame(expected["frame_hex"])
    assert isinstance(decoded, MeasurementFrame)
    assert decoded.weight_kg == 78.9
    # Layout bits still claim a word block, but values are all zero.
    assert decoded.b5 == 0x01 and decoded.b6 == 0x21
    assert decoded.word_block == [0, 0, 0, 0, 0]
    assert session["decode_hypotheses"]["opaque_words_all_zero_count"] > 0
    assert session["decode_hypotheses"]["opaque_words_nonzero_count"] == 0


def test_condition_notifications_all_checksum_ok() -> None:
    for path in (GROUNDED, UNPLUGGED):
        session, _expected = _load(path)
        for record in session["notifications"]:
            frame = decode_frame(record["hex"])
            assert frame.checksum_valid is True


def test_sanitized_quality_fixtures_are_address_and_timestamp_free() -> None:
    for path in POLICY_FIXTURES:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        assert fixture["sanitized"] is True
        assert "address" not in json.dumps(fixture).casefold()
        assert "timestamp" not in json.dumps(fixture).casefold()


def test_quality_acceptance_requires_persisted_ack_evidence() -> None:
    fixture = json.loads(
        (CONDITION_ROOT / "handle_contact_complete.json").read_text(encoding="utf-8")
    )
    policy = AcquisitionCompletionPolicy(stable_measurements=3, idle_seconds=0.01)
    for raw in fixture["notifications"]:
        policy.observe_wire("rx", bytes.fromhex(raw))
        policy.observe(decode_frame(raw))

    decision = policy.finish("stream_closed")

    assert decision.quality is MeasurementQuality.INDETERMINATE
    assert decision.reason == "stable_complete_word_burst_missing_ack_evidence"
    assert policy.acknowledgment_observed is False


def test_sanitized_quality_fixtures_drive_separate_policy_outcomes() -> None:
    expected = {
        "handle_contact_complete.json": MeasurementQuality.ACCEPTED,
        "foot_only_contact_failed.json": MeasurementQuality.CONTACT_FAILED,
        "foot_only_interrupted.json": MeasurementQuality.INDETERMINATE,
    }
    for path in POLICY_FIXTURES:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        policy = AcquisitionCompletionPolicy(stable_measurements=3, idle_seconds=0.01)
        observed_decisions = []
        for raw in fixture["notifications"]:
            event = decode_frame(raw)
            policy.observe_wire("rx", bytes.fromhex(raw))
            observed_decisions.append(policy.observe(event))
            if isinstance(event, MeasurementFrame) and (event.b5, event.b6) == (1, 0x21):
                policy.observe_wire("tx", bytes.fromhex(fixture["ack_hex"]))
        assert all(decision is None for decision in observed_decisions)
        decision = policy.finish(fixture["expected_completion"])
        assert decision.quality is expected[path.name]
        assert decision.quality.value == fixture["expected_quality"]


def test_separated_marker_runs_cannot_form_stable_quality() -> None:
    fixture = json.loads(
        (CONDITION_ROOT / "handle_contact_complete.json").read_text(encoding="utf-8")
    )
    notifications = fixture["notifications"]
    # Two A frames, two B frames, then an intervening A frame. A global
    # occurrence counter would incorrectly combine the separated runs.
    selected = notifications[3:5] + notifications[6:8] + notifications[3:4]
    policy = AcquisitionCompletionPolicy(stable_measurements=2, idle_seconds=0.01)
    for raw in selected:
        event = decode_frame(raw)
        policy.observe_wire("rx", bytes.fromhex(raw))
        policy.observe(event)
        if isinstance(event, MeasurementFrame) and (event.b5, event.b6) == (1, 0x21):
            policy.observe_wire("tx", bytes.fromhex(fixture["ack_hex"]))

    decision = policy.finish("intervening_frame")

    assert decision.quality is MeasurementQuality.INDETERMINATE


def test_invalid_frame_breaks_pending_burst_assembly() -> None:
    fixture = json.loads(
        (CONDITION_ROOT / "handle_contact_complete.json").read_text(encoding="utf-8")
    )
    packet1 = bytes.fromhex(fixture["notifications"][3])
    invalid = bytearray(packet1)
    invalid[-1] ^= 1
    packet2 = bytes.fromhex(fixture["notifications"][6])
    policy = AcquisitionCompletionPolicy(stable_measurements=2, idle_seconds=0.01)

    for raw in (packet1, packet1, bytes(invalid), packet2, packet2):
        event = decode_frame(raw)
        policy.observe_wire("rx", raw)
        policy.observe(event)
        if isinstance(event, MeasurementFrame) and (event.b5, event.b6) == (1, 0x21):
            policy.observe_wire("tx", bytes.fromhex(fixture["ack_hex"]))

    assert policy.latest_burst is None
    assert policy.finish("invalid_interruption").quality is MeasurementQuality.INDETERMINATE
