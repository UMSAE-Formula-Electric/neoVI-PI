"""
telemetry.wire.frame_source — the D-08 pluggable frame-source contract.

`RawFrame` is the raw, undecoded CAN frame shape the rest of `telemetry.wire`
consumes. It mirrors the raw tuple already used by `src/new_logger.py`'s
`capture_thread` (timestamp first, payload last: lines 202-208), formalized
as a `NamedTuple` plus a `Protocol` so a future real-log reader (Phase 1) can
be dropped in with zero change to the encoder or the measurement tool. The
synthetic generator (`telemetry.synth.generator.SyntheticFrameSource`) is the
only implementation that exists in Phase 0 — nothing else lives here.
"""

from typing import Iterator, NamedTuple, Protocol


class RawFrame(NamedTuple):
    """One raw, undecoded CAN frame — the frame_id/is_extended pair identifies
    the message per D-05; DLC is implied by `len(payload)`."""

    timestamp_us: int
    frame_id: int
    is_extended: bool
    payload: bytes


class FrameSource(Protocol):
    """Anything that can produce a stream of `RawFrame`s. `SyntheticFrameSource`
    is the Phase 0 implementation; a real-log (`.vsb`/`.blf`/`.asc`) reader is
    the deferred Phase 1 implementation (D-08) — both satisfy this same
    contract with no change required in `encoder.py` or `measure/report.py`."""

    def frames(self) -> Iterator[RawFrame]: ...
