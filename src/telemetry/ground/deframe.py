"""
telemetry.ground.deframe — `Deframer`, the byte-stream-to-`RawFrame`
half of the ground station (GND-01, LINK-02, T-01-01, T-01-05).

A byte-stream interface (`feed(data: bytes)`), not a datagram interface,
is what lets the same deframer serve UDP now and a serial port in Phase 9
with no change above it — `feed` accumulates bytes across calls, splits on
the `0x00` COBS delimiter, and for each complete segment unframes, splits
the batch, and CFR-decodes each record, yielding a list of `RawFrame` per
successfully recovered batch.

Every layer of this chain — COBS decode, CRC verify, batch split, CFR
decode — raises a specific, caught exception type
(`telemetry.framing.errors.CobsDecodeFailed`/`CrcMismatch`/
`BatchFormatError`, `telemetry.wire.decoder.DecodeError`), each counted on
`DeframeCounters` and skipped. No unhandled exception can reach and kill
the consumer loop (T-01-01) — a corrupt batch is discarded and counted,
never passed upstream and never allowed to terminate the loop.

The accumulation buffer is capped at `max_buffer_bytes`; a stream that
never presents a delimiter has its pending bytes discarded and the event
counted (`buffer_overflow_count`) rather than growing memory without bound
(T-01-05).
"""

import logging
from dataclasses import dataclass
from typing import Iterator, List, Optional

from telemetry.framing.cobs_frame import unframe
from telemetry.framing.errors import BatchFormatError, CobsDecodeFailed, CrcMismatch
from telemetry.wire.batcher import split_batch
from telemetry.wire.decoder import Decoder, DecodeError
from telemetry.wire.dictionary import IdDictionary
from telemetry.wire.encoder import EncoderOptions
from telemetry.wire.frame_source import RawFrame

logger = logging.getLogger(__name__)

# A generously large default — sized well above any Phase-1-plausible batch
# (01-RESEARCH.md Pattern 6's UDP recvfrom pitfall applies to this cap too:
# too tight, and a legitimate large batch gets discarded and miscounted as
# corruption). Callers with a config-known max batch size should pass their
# own value.
DEFAULT_MAX_BUFFER_BYTES = 65536


@dataclass
class DeframeCounters:
    """Per-`Deframer` corruption/recovery counters (LINK-02, T-01-01,
    T-01-05) — every discard is counted, never silent."""

    batches_ok: int = 0
    cobs_failures: int = 0
    crc_failures: int = 0
    batch_format_failures: int = 0
    records_decoded: int = 0
    record_decode_failures: int = 0
    buffer_overflow_count: int = 0


class Deframer:
    """Accumulates bytes across `feed()` calls, yielding a list of
    `RawFrame` per successfully recovered batch. Must be constructed with
    the same `EncoderOptions` the car-side `Encoder` used — a caller
    contract, not something negotiated over the wire (Phase 4 scope)."""

    def __init__(
        self,
        dictionary: IdDictionary,
        options: Optional[EncoderOptions] = None,
        max_buffer_bytes: int = DEFAULT_MAX_BUFFER_BYTES,
    ) -> None:
        self._decoder = Decoder(dictionary, options)
        self._buffer = bytearray()
        self._max_buffer_bytes = max_buffer_bytes
        self.counters = DeframeCounters()

    def feed(self, data: bytes) -> Iterator[List[RawFrame]]:
        """Feed newly-arrived bytes. Yields one `list[RawFrame]` per
        complete, successfully-decoded batch found in the accumulated
        stream. Never raises — every failure is counted and skipped."""
        self._buffer.extend(data)

        while True:
            delimiter_index = self._buffer.find(0x00)
            if delimiter_index == -1:
                break
            segment = bytes(self._buffer[:delimiter_index])
            del self._buffer[: delimiter_index + 1]
            if not segment:
                continue
            recovered = self._process_segment(segment)
            if recovered is not None:
                yield recovered

        if len(self._buffer) > self._max_buffer_bytes:
            logger.warning(
                "deframe accumulation buffer exceeded %d bytes with no "
                "delimiter present — discarding pending bytes",
                self._max_buffer_bytes,
            )
            self.counters.buffer_overflow_count += 1
            self._buffer = bytearray()

    def _process_segment(self, segment: bytes) -> Optional[List[RawFrame]]:
        try:
            payload = unframe(segment)
        except CobsDecodeFailed as exc:
            logger.info("discarding corrupt segment: %s", exc)
            self.counters.cobs_failures += 1
            return None
        except CrcMismatch as exc:
            logger.info("discarding corrupt segment: %s", exc)
            self.counters.crc_failures += 1
            return None

        try:
            header, records = split_batch(payload)
        except BatchFormatError as exc:
            logger.info("discarding malformed batch: %s", exc)
            self.counters.batch_format_failures += 1
            return None

        self.counters.batches_ok += 1

        recovered: List[RawFrame] = []
        for record in records:
            try:
                frame = self._decoder.decode(record, header.base_timestamp_us)
            except DecodeError as exc:
                logger.info("discarding undecodable record: %s", exc)
                self.counters.record_decode_failures += 1
                continue
            recovered.append(frame)
            self.counters.records_decoded += 1

        return recovered
