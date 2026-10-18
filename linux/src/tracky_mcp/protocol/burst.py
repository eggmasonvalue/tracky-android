"""Opaque assembly of the observed two-packet CS10B word burst.

The packet order and five-word boundaries are protocol evidence.  Nothing in
this module names a word as a channel, impedance, resistance, frequency, or
body-composition value.
"""

from __future__ import annotations

from dataclasses import dataclass

from .decode import MeasurementFrame

WORD_BLOCK_LENGTH = 5
PACKET_ONE_MARKER = (0x01, 0x21)
PACKET_TWO_MARKER = (0x01, 0x22)


@dataclass(frozen=True, slots=True)
class OpaqueBurst:
    """One assembled, wire-valid pair of five-word blocks."""

    packet1: MeasurementFrame
    packet2: MeasurementFrame

    def __post_init__(self) -> None:
        if (self.packet1.b5, self.packet1.b6) != PACKET_ONE_MARKER:
            raise ValueError("packet1 must have b5=0x01 and b6=0x21")
        if (self.packet2.b5, self.packet2.b6) != PACKET_TWO_MARKER:
            raise ValueError("packet2 must have b5=0x01 and b6=0x22")
        if len(self.packet1.word_block) != WORD_BLOCK_LENGTH:
            raise ValueError("packet1 must contain five opaque words")
        if len(self.packet2.word_block) != WORD_BLOCK_LENGTH:
            raise ValueError("packet2 must contain five opaque words")

    @property
    def wire_valid(self) -> bool:
        """Whether both source frames passed their checksum/shape checks."""

        return self.packet1.wire_valid and self.packet2.wire_valid

    @property
    def block_a(self) -> tuple[int, ...]:
        """The first observed five-word block, in wire order."""

        return tuple(self.packet1.word_block)

    @property
    def block_b(self) -> tuple[int, ...]:
        """The second observed five-word block, in wire order."""

        return tuple(self.packet2.word_block)

    @property
    def opaque_words(self) -> tuple[int, ...]:
        """Both blocks concatenated without assigning semantic labels."""

        return self.block_a + self.block_b

    @property
    def weight_raw_u16_be(self) -> int:
        """Use the second packet's observed weight, falling back to packet one."""

        return (
            self.packet2.weight_raw_u16_be
            if self.packet2.weight_raw_u16_be > 0
            else self.packet1.weight_raw_u16_be
        )


class BurstAssembler:
    """Assemble only ordered, checksum-valid packet pairs.

    A bad-checksum frame can still be retained by the caller as wire evidence,
    but it can never become a burst input.  The assembler has no quality
    opinion; contact/quality classification is a separate policy layer.
    """

    def __init__(self) -> None:
        self.pending_packet1: MeasurementFrame | None = None
        self.completed: list[OpaqueBurst] = []

    def add(self, frame: MeasurementFrame) -> OpaqueBurst | None:
        """Accept a valid measurement frame and return a new burst if complete."""

        if not isinstance(frame, MeasurementFrame) or not frame.wire_valid:
            self.interrupt()
            return None
        marker = (frame.b5, frame.b6)
        if marker == PACKET_ONE_MARKER:
            if len(frame.word_block) == WORD_BLOCK_LENGTH:
                self.pending_packet1 = frame
            return None
        if marker != PACKET_TWO_MARKER or self.pending_packet1 is None:
            if marker != PACKET_TWO_MARKER:
                self.pending_packet1 = None
            return None
        if len(frame.word_block) != WORD_BLOCK_LENGTH:
            self.pending_packet1 = None
            return None

        burst = OpaqueBurst(self.pending_packet1, frame)
        self.completed.append(burst)
        self.pending_packet1 = None
        return burst

    def interrupt(self) -> None:
        """Break a pending packet pair without deleting completed evidence."""

        self.pending_packet1 = None

    def reset(self) -> None:
        """Discard pending and completed assembly state for a new connection."""

        self.pending_packet1 = None
        self.completed.clear()


def reassemble_burst(packet1: MeasurementFrame, packet2: MeasurementFrame) -> OpaqueBurst:
    """Assemble two packet frames without interpreting their opaque words."""

    if not packet1.wire_valid or not packet2.wire_valid:
        raise ValueError("burst packets must both be wire-valid")
    return OpaqueBurst(packet1, packet2)


__all__ = [
    "BurstAssembler",
    "OpaqueBurst",
    "PACKET_ONE_MARKER",
    "PACKET_TWO_MARKER",
    "WORD_BLOCK_LENGTH",
    "reassemble_burst",
]
