"""Evidence-backed quality and completion policy for live acquisitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from .burst import PACKET_ONE_MARKER, PACKET_TWO_MARKER, BurstAssembler, OpaqueBurst
from .decode import DecodedFrame, MeasurementFrame, decode_frame

QUALITY_VERSION: Final[int] = 1
WEIGHT_SELECTION_POLICY_VERSION: Final[int] = 1
_ACK_WRITE = bytes.fromhex("1f0620102176")
Marker = tuple[int, int]
RunKey = tuple[Marker, int, tuple[int, ...]]


class MeasurementQuality(str, Enum):
    """Quality of the observed acquisition, independent of wire validity."""

    ACCEPTED = "accepted"
    CONTACT_FAILED = "contact_failed"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class CompletionDecision:
    """A terminal recording decision made from retained wire evidence."""

    quality: MeasurementQuality
    reason: str
    quality_version: int = QUALITY_VERSION
    selection_policy_version: int = WEIGHT_SELECTION_POLICY_VERSION
    selected_frame_raw: bytes | None = None


class AcquisitionCompletionPolicy:
    """Classify evidence after capture has reached an idle/terminal boundary.

    The live captures show runs of repeated, wire-valid measurement frames. A
    run is tracked for one marker and one complete frame signature only;
    changing markers, changing values, invalid frames, and intervening frames
    break it. A packet pair can make capture eligible for the configured idle
    grace period, but this policy never ends capture directly from ``observe``.

    The exact packet-1 acknowledgment is accepted as evidence only through
    :meth:`observe_wire` with a persisted TX event. RX packet order alone is not
    represented as ACK validation. Missing ACK evidence therefore produces an
    indeterminate result rather than an accepted quality.
    """

    def __init__(
        self,
        *,
        stable_measurements: int = 3,
        idle_seconds: float = 3.0,
    ) -> None:
        if stable_measurements < 2:
            raise ValueError("stable_measurements must be at least 2")
        if idle_seconds <= 0:
            raise ValueError("idle_seconds must be greater than zero")
        self.stable_measurements = stable_measurements
        self.idle_seconds = idle_seconds
        self.assembler = BurstAssembler()
        self.measurements: list[MeasurementFrame] = []
        self._active_marker: Marker | None = None
        self._active_signature: tuple[int, tuple[int, ...]] | None = None
        self._active_count = 0
        self._completed_runs: dict[RunKey, int] = {}
        self._latest_burst: OpaqueBurst | None = None
        self._latest_burst_run_keys: tuple[RunKey, RunKey] | None = None
        self._latest_burst_ack_observed = False
        self._burst_interrupted = False
        self._wire_pending_packet1 = False
        self._wire_ack_for_pending_packet = False
        self._wire_ack_for_latest_pair = False
        self._last_decision: CompletionDecision | None = None
        self._weight_signature: tuple[int, int, str] | None = None
        self._weight_run_count = 0
        self._selected_frame_raw: bytes | None = None

    @property
    def latest_measurement(self) -> MeasurementFrame | None:
        return self.measurements[-1] if self.measurements else None

    @property
    def consecutive_measurements(self) -> int:
        return self._active_count

    @property
    def has_wire_valid_measurement(self) -> bool:
        return bool(self.measurements)

    @property
    def can_finish_after_idle(self) -> bool:
        """Whether evidence makes the stream eligible for its idle grace."""

        return (
            self._active_count >= self.stable_measurements
            or self._latest_burst is not None
        )

    @property
    def latest_burst(self) -> OpaqueBurst | None:
        return self._latest_burst

    @property
    def acknowledgment_observed(self) -> bool:
        """Whether the exact packet-1 ACK was observed on the TX wire."""

        return self._latest_burst_ack_observed

    def observe_wire(self, direction: str, data: bytes | bytearray | memoryview) -> None:
        """Observe a persisted wire event relevant to completion evidence.

        Only a successful TX event carrying the exact observed ACK counts. The
        acquisition service calls this after appending the event to storage.
        """

        raw = bytes(data)
        if direction == "tx":
            if raw == _ACK_WRITE and self._wire_pending_packet1:
                self._wire_ack_for_pending_packet = True
            return
        if direction != "rx":
            return
        try:
            decoded = decode_frame(raw)
        except ValueError:
            self._break_wire_sequence()
            return
        if not isinstance(decoded, MeasurementFrame) or not decoded.wire_valid:
            self._break_wire_sequence()
            return
        marker = (decoded.b5, decoded.b6)
        if marker == PACKET_ONE_MARKER:
            self._wire_pending_packet1 = True
            self._wire_ack_for_pending_packet = False
        elif marker == PACKET_TWO_MARKER and self._wire_pending_packet1:
            self._wire_ack_for_latest_pair = self._wire_ack_for_pending_packet
            self._wire_pending_packet1 = False
            self._wire_ack_for_pending_packet = False
        else:
            self._break_wire_sequence()

    def observe(self, event: DecodedFrame) -> None:
        """Observe one decoded event without making a terminal decision."""

        if not isinstance(event, MeasurementFrame) or not event.wire_valid:
            self._break_sequence()
            return

        marker = (event.b5, event.b6)
        signature = (event.weight_raw_u16_be, tuple(event.word_block))
        if self._latest_burst is not None and not self._continues_latest_packet2(
            marker, signature
        ):
            self._burst_interrupted = True

        self._advance_run(marker, signature)
        self._advance_weight_selection(event)
        self.measurements.append(event)

        burst = self.assembler.add(event)
        if burst is not None:
            self._latest_burst = burst
            self._latest_burst_run_keys = (
                self._run_key(burst.packet1),
                self._run_key(burst.packet2),
            )
            self._latest_burst_ack_observed = self._wire_ack_for_latest_pair
            self._burst_interrupted = False
            self._wire_ack_for_latest_pair = False

    def finish(self, reason: str) -> CompletionDecision:
        """Classify evidence after idle, stream close, or explicit stop."""

        if self._last_decision is not None:
            return self._last_decision
        self._commit_active_run()

        latest = self.latest_measurement
        if latest is None:
            return self._remember(MeasurementQuality.INDETERMINATE, "no_wire_valid_measurement")

        burst = self._latest_burst
        if burst is not None:
            if self._stable_burst_blocks(burst):
                if self._latest_burst_ack_observed:
                    if self._all_zero(burst.opaque_words):
                        return self._remember(
                            MeasurementQuality.CONTACT_FAILED,
                            "stable_complete_zero_word_burst",
                        )
                    return self._remember(
                        MeasurementQuality.ACCEPTED,
                        "stable_complete_word_burst",
                    )
                return self._remember(
                    MeasurementQuality.INDETERMINATE,
                    "stable_complete_word_burst_missing_ack_evidence",
                )
            if self._all_zero(burst.opaque_words):
                return self._remember(
                    MeasurementQuality.INDETERMINATE,
                    "incomplete_zero_word_burst",
                )

        if self._all_zero(latest.word_block) and self._active_count >= self.stable_measurements:
            return self._remember(MeasurementQuality.CONTACT_FAILED, "stable_zero_word_block")

        if self._active_count >= self.stable_measurements:
            return self._remember(
                MeasurementQuality.INDETERMINATE,
                "stable_measurement_without_accepted_word_burst",
            )
        return self._remember(MeasurementQuality.INDETERMINATE, reason)

    def _advance_weight_selection(self, event: MeasurementFrame) -> None:
        """Select only a repeated, wire-valid display-weight observation.

        The policy intentionally uses the independently validated display-weight
        field only. Opaque word blocks never participate in this selection.
        """

        signature = (
            event.weight_raw_u16_be,
            event.weight_scale_divisor,
            event.weight_unit,
        )
        if signature == self._weight_signature:
            self._weight_run_count += 1
        else:
            self._weight_signature = signature
            self._weight_run_count = 1
        if (
            event.weight_raw_u16_be > 0
            and self._weight_run_count >= self.stable_measurements
        ):
            self._selected_frame_raw = bytes(event.raw)

    def _advance_run(self, marker: Marker, signature: tuple[int, tuple[int, ...]]) -> None:
        if marker == self._active_marker and signature == self._active_signature:
            self._active_count += 1
            return
        self._commit_active_run()
        self._active_marker = marker
        self._active_signature = signature
        self._active_count = 1

    def _commit_active_run(self) -> None:
        if self._active_marker is None or self._active_signature is None:
            return
        weight_raw, words = self._active_signature
        self._completed_runs[(self._active_marker, weight_raw, words)] = self._active_count
        self._active_marker = None
        self._active_signature = None
        self._active_count = 0

    def _break_sequence(self) -> None:
        self._commit_active_run()
        self._weight_signature = None
        self._weight_run_count = 0
        self.assembler.interrupt()
        self._break_wire_sequence()
        if self._latest_burst is not None:
            self._burst_interrupted = True

    def _break_wire_sequence(self) -> None:
        self._wire_pending_packet1 = False
        self._wire_ack_for_pending_packet = False
        self._wire_ack_for_latest_pair = False

    def _stable_burst_blocks(self, burst: OpaqueBurst) -> bool:
        if self._burst_interrupted or self._latest_burst_run_keys is None:
            return False
        key_a, key_b = self._latest_burst_run_keys
        return (
            self._completed_runs.get(key_a, 0) >= self.stable_measurements
            and self._completed_runs.get(key_b, 0) >= self.stable_measurements
        )

    def _continues_latest_packet2(
        self,
        marker: Marker,
        signature: tuple[int, tuple[int, ...]],
    ) -> bool:
        if self._latest_burst is None:
            return True
        return (
            marker == PACKET_TWO_MARKER
            and signature == self._run_signature(self._latest_burst.packet2)
        )

    @staticmethod
    def _run_signature(frame: MeasurementFrame) -> tuple[int, tuple[int, ...]]:
        return frame.weight_raw_u16_be, tuple(frame.word_block)

    @staticmethod
    def _run_key(frame: MeasurementFrame) -> RunKey:
        return (frame.b5, frame.b6), frame.weight_raw_u16_be, tuple(frame.word_block)

    @staticmethod
    def _all_zero(values: tuple[int, ...] | list[int]) -> bool:
        return bool(values) and all(value == 0 for value in values)

    def _remember(self, quality: MeasurementQuality, reason: str) -> CompletionDecision:
        if self._last_decision is None:
            self._last_decision = CompletionDecision(
                quality=quality,
                reason=reason,
                selected_frame_raw=self._selected_frame_raw,
            )
        return self._last_decision


# Short name for callers that want the policy without the implementation detail.
CompletionPolicy = AcquisitionCompletionPolicy


__all__ = [
    "AcquisitionCompletionPolicy",
    "CompletionDecision",
    "CompletionPolicy",
    "MeasurementQuality",
    "QUALITY_VERSION",
    "WEIGHT_SELECTION_POLICY_VERSION",
]
