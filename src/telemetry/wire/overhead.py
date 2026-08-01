"""
telemetry.wire.overhead — the D-06 analytic framing overhead formula.

Computed, never implemented: no COBS or CRC-16 implementation exists in this
phase (or anywhere in this repository), and neither a `cobs` nor a `crc`
package is installed as a dependency. The three constants below are quoted
directly from the already-settled wire-format design
(`.planning/research/ARCHITECTURE.md` Pattern 3), and every function in this
module is pure arithmetic over them. Phase 1 owns the real framing
implementation (batching, COBS encode/decode, CRC-16 compute/check) that
these numbers describe in advance.

The 13-byte batch header (`BATCH_HEADER_BYTES`) is the sum of four fields:
    - protocol_version:  1 byte
    - dict_version:      1 byte
    - base timestamp:    8 bytes
    - frame_count:       2 bytes
    - batch_seq:         1 byte
    1 + 1 + 8 + 2 + 1 = 13

`CRC16_BYTES` (2) is the trailing CRC-16 checksum appended to a batch's
encoded frame bytes. `COBS_BLOCK_BYTES` (254) is COBS's maximum run of
non-zero bytes between overhead bytes — the closed-form worst case is one
extra overhead byte per started (or partial) 254-byte block:
`payload_bytes // COBS_BLOCK_BYTES + 1`.

This module must not import from `telemetry.synth` or `telemetry.measure` —
it describes the wire format those packages measure against, never the
other way around.
"""

from dataclasses import dataclass

BATCH_HEADER_BYTES = 13  # protocol_version(1) + dict_version(1) + base_timestamp(8) + frame_count(2) + batch_seq(1)
CRC16_BYTES = 2
COBS_BLOCK_BYTES = 254


def cobs_worst_case_overhead(payload_bytes: int) -> int:
    """The closed-form COBS worst-case overhead byte count for a payload of
    `payload_bytes` bytes: one overhead byte per started 254-byte block."""
    return payload_bytes // COBS_BLOCK_BYTES + 1


def all_in_bytes_per_batch(clean_payload_bytes: int) -> int:
    """header + (clean + crc) + cobs(clean + crc) — the all-in byte count
    for one batch whose clean CFR payload totals `clean_payload_bytes`
    bytes."""
    framed = clean_payload_bytes + CRC16_BYTES
    return BATCH_HEADER_BYTES + framed + cobs_worst_case_overhead(framed)


@dataclass(frozen=True)
class OverheadBreakdown:
    """One batch's clean-versus-all-in split, plus every component that
    produced it, so a reader can check the formula without recomputing it
    from source."""

    clean_payload_bytes: int
    batch_header_bytes: int
    crc_bytes: int
    cobs_bytes: int
    all_in_bytes: int
    frames_in_batch: int
    clean_bytes_per_frame: float
    all_in_bytes_per_frame: float
    overhead_pct: float


def overhead_breakdown(clean_payload_bytes: int, frames_in_batch: int) -> OverheadBreakdown:
    """Compute the full clean-versus-all-in breakdown for one batch.

    Raises `ValueError` naming `frames_in_batch` for a non-positive batch
    size, rather than dividing by zero."""
    if frames_in_batch <= 0:
        raise ValueError(
            f"frames_in_batch must be a positive integer, got {frames_in_batch!r}"
        )

    framed = clean_payload_bytes + CRC16_BYTES
    cobs_bytes = cobs_worst_case_overhead(framed)
    all_in_bytes = BATCH_HEADER_BYTES + framed + cobs_bytes

    clean_bytes_per_frame = clean_payload_bytes / frames_in_batch
    all_in_bytes_per_frame = all_in_bytes / frames_in_batch
    overhead_pct = (
        (all_in_bytes - clean_payload_bytes) / clean_payload_bytes * 100
        if clean_payload_bytes
        else 0.0
    )

    return OverheadBreakdown(
        clean_payload_bytes=clean_payload_bytes,
        batch_header_bytes=BATCH_HEADER_BYTES,
        crc_bytes=CRC16_BYTES,
        cobs_bytes=cobs_bytes,
        all_in_bytes=all_in_bytes,
        frames_in_batch=frames_in_batch,
        clean_bytes_per_frame=clean_bytes_per_frame,
        all_in_bytes_per_frame=all_in_bytes_per_frame,
        overhead_pct=overhead_pct,
    )
