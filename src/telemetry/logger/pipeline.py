"""
telemetry.logger.pipeline — `TelemetryPipeline`, the consumer end of
`FanOut.telemetry_queue` (CAP-05/CAP-06 for the live path): drain, batch,
encode, frame, send, on its own thread. This is where the tracer's one-frame
proof (01-04) becomes a real batching loop someone can run unattended.

**Batch closing is a race between three conditions**, whichever comes first:

- the configured frame count (`batch_frames`);
- the configured maximum batch age (`batch_max_age_s`), checked both after
  every frame added and, independently, while the queue sits idle — so a
  quiet bus still delivers within the configured latency rather than
  waiting for a full batch that may never arrive;
- the CFR delta-t window `telemetry.wire.encoder` enforces. This third
  condition is a correctness requirement, not a tuning knob (01-CONTEXT.md
  critical constraint #2): `Encoder.encode()` raises `BatchWindowExceeded`
  when a frame's timestamp would fall outside the batch's representable
  delta-t window, and this module closes the batch in progress and lets the
  frame that triggered the close open the next one, rather than letting the
  exception surface as a lost frame. `config/logger.json`'s
  `telemetry.batch_max_age_s` is already validated at load time
  (`telemetry.logger.config`) to sit strictly below this window, so in
  practice the age trigger fires first on a real clock — the window trigger
  exists for the case a batch is built from timestamps that are not paced
  by wall-clock time (e.g. a replayed or synthetic source), where age alone
  would never catch it.

**Sending is** pack the batch (`telemetry.wire.batcher.pack_batch`), frame
it with CRC-16 and COBS (`telemetry.framing.cobs_frame.frame`), then one
`Link.send()` call — nothing else. The link is whatever `config/logger.json`
selected; this module neither knows nor cares which implementation it holds
(`telemetry.link.base.Link`).

**Every failure is caught by its specific type, counted, and logged with
frame or batch context — none of them may terminate the thread.** The live
path is lossy by design (`01-CONTEXT.md`'s drop-oldest decision), and the
archive path holds no reference to any of this module's state, so nothing
here can ever cost the archive a frame:

- `PayloadTooLong` / `UnknownFrameId` (an id absent from the encoder's
  dictionary, or a payload over the CAN DLC maximum) — each counted on its
  own named field. `FanOut`'s own CAP-06 precheck (01-07) already filters
  most of these before a frame ever reaches the telemetry deque when
  constructed with a real dictionary; this is the defence-in-depth second
  check for whatever precheck configuration didn't catch.
- Any other `CfrError` — counted separately as `unexpected_cfr_error_count`,
  never silently dropped.
- `FramingError` (a `pack_batch`/`frame` failure) — counted and logged;
  the batch that failed to frame is discarded (there is nothing safe left
  to send), not retried.
- A `Link.send()` exception of any kind — counted and logged; the pipeline
  keeps running. A transmit failure must never propagate into the capture
  or archive path (T-01-26).

**On the stop event, the pipeline flushes the batch in progress before
returning** — frames already popped off the deque and encoded into an
open batch must not be silently discarded by a shutdown, even though the
live path may otherwise drop anything still sitting in the deque itself
(that is what "lossy by design" means).

Thread discipline mirrors `telemetry.archive.runner.ArchiveRunner`: name the
thread, poll the shared stop event, flush before returning. Unlike the
archive runner, this thread is a daemon — it carries no durability
obligation, and that asymmetry is the entire point of the fan-out.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

from telemetry.capture.fanout import CapturedFrame
from telemetry.framing.cobs_frame import frame as cobs_frame
from telemetry.framing.errors import FramingError
from telemetry.link.base import Link
from telemetry.wire.batcher import pack_batch
from telemetry.wire.dictionary import UnknownFrameId
from telemetry.wire.encoder import (
    BatchWindowExceeded,
    CfrError,
    Encoder,
    PayloadTooLong,
)

logger = logging.getLogger(__name__)

_DEFAULT_POLL_TIMEOUT_S = 0.05
_DEFAULT_THREAD_NAME = "telemetry-pipeline"

# batch_seq is the batch header's one-byte field (telemetry.wire.batcher
# BATCH_HEADER_STRUCT's "<BBQHB" — the trailing B) — wraps at 256, not
# restated as a bare literal at the wrap site below.
_BATCH_SEQ_MODULUS = 256


@dataclass
class TelemetryPipelineCounters:
    """Mutable counters this pipeline's shutdown report reads (CAP-05/06 for
    the live path): throughput, and every reason a frame or a batch could
    not be carried, each on its own named field so the live path's loss
    rate is a set of exact numbers, never an inference. Written only by
    this pipeline's own thread; safe to read from other threads only after
    `join()` — the same single-writer rationale as
    `telemetry.capture.fanout.FanOutCounters`."""

    frames_sent: int = 0
    batches_sent: int = 0
    bytes_sent: int = 0

    unknown_id_count: int = 0
    payload_too_long_count: int = 0
    unexpected_cfr_error_count: int = 0

    framing_error_count: int = 0
    link_send_failure_count: int = 0


class TelemetryPipeline:
    """Drains `telemetry_queue` (a `collections.deque`, not a
    `queue.Queue` — `FanOut` owns a plain bounded deque for the telemetry
    side) into batches, frames each batch, and sends it over `link` on its
    own daemon thread."""

    def __init__(
        self,
        telemetry_queue: Deque[CapturedFrame],
        encoder: Encoder,
        link: Link,
        dict_version: int,
        batch_frames: int,
        batch_max_age_s: float,
        stop_event: threading.Event,
        counters: Optional[TelemetryPipelineCounters] = None,
        poll_timeout_s: float = _DEFAULT_POLL_TIMEOUT_S,
        name: str = _DEFAULT_THREAD_NAME,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._telemetry_queue = telemetry_queue
        self._encoder = encoder
        self._link = link
        self._dict_version = dict_version
        self._batch_frames = batch_frames
        self._batch_max_age_s = batch_max_age_s
        self._stop_event = stop_event
        self.counters = counters if counters is not None else TelemetryPipelineCounters()
        self._poll_timeout_s = poll_timeout_s
        self._clock = clock

        self._batch_records: List[bytes] = []
        self._batch_base_timestamp_us: Optional[int] = None
        self._batch_started_at: float = 0.0
        self._batch_seq: int = 0

        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def join(self, timeout: Optional[float] = None) -> None:
        self.thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                captured = self._telemetry_queue.popleft()
            except IndexError:
                if self._batch_age_exceeded():
                    self._close_and_send_batch()
                self._stop_event.wait(timeout=self._poll_timeout_s)
                continue
            self._handle_frame(captured)

        # Frames already drained from the deque into an open batch must not
        # be silently discarded by a shutdown, even though the live path is
        # otherwise lossy by design for anything still sitting in the deque
        # itself.
        self._close_and_send_batch()

    def _handle_frame(self, captured: CapturedFrame) -> None:
        if not self._batch_records:
            self._start_new_batch(captured.frame.timestamp_us)

        cfr = self._encode_frame(captured)
        if cfr is None:
            return

        self._batch_records.append(cfr)
        self.counters.frames_sent += 1

        if len(self._batch_records) >= self._batch_frames or self._batch_age_exceeded():
            self._close_and_send_batch()

    def _encode_frame(self, captured: CapturedFrame) -> Optional[bytes]:
        """One encode attempt against the current batch's base timestamp.
        Returns the CFR bytes, or `None` having already recorded and
        logged a specific, named error — never raises."""
        frame = captured.frame
        try:
            return self._encoder.encode(frame, self._batch_base_timestamp_us)
        except BatchWindowExceeded:
            # Correctness requirement (01-CONTEXT.md critical constraint
            # #2), not a tuning knob: close the batch in progress and let
            # this frame open the next one, rather than letting the
            # exception surface as a lost frame.
            self._close_and_send_batch()
            self._start_new_batch(frame.timestamp_us)
            try:
                return self._encoder.encode(frame, self._batch_base_timestamp_us)
            except (PayloadTooLong, UnknownFrameId, CfrError) as exc:
                self._record_encode_error(captured, exc)
                return None
        except (PayloadTooLong, UnknownFrameId, CfrError) as exc:
            self._record_encode_error(captured, exc)
            return None

    def _record_encode_error(self, captured: CapturedFrame, exc: Exception) -> None:
        if isinstance(exc, PayloadTooLong):
            counter_name = "payload_too_long_count"
        elif isinstance(exc, UnknownFrameId):
            counter_name = "unknown_id_count"
        else:
            counter_name = "unexpected_cfr_error_count"
        setattr(self.counters, counter_name, getattr(self.counters, counter_name) + 1)

        frame = captured.frame
        logger.warning(
            "telemetry pipeline could not encode frame (channel=%s "
            "frame_id=0x%X is_extended=%s timestamp_us=%d): %s — archive "
            "path unaffected",
            captured.channel,
            frame.frame_id,
            frame.is_extended,
            frame.timestamp_us,
            exc,
        )

    def _start_new_batch(self, base_timestamp_us: int) -> None:
        self._batch_records = []
        self._batch_base_timestamp_us = base_timestamp_us
        self._batch_started_at = self._clock()

    def _batch_age_exceeded(self) -> bool:
        if not self._batch_records:
            return False
        return (self._clock() - self._batch_started_at) >= self._batch_max_age_s

    def _close_and_send_batch(self) -> None:
        if not self._batch_records:
            return

        record_count = len(self._batch_records)
        try:
            payload = pack_batch(
                dict_version=self._dict_version,
                base_timestamp_us=self._batch_base_timestamp_us,
                batch_seq=self._batch_seq,
                records=self._batch_records,
            )
            framed = cobs_frame(payload)
        except FramingError as exc:
            logger.error(
                "telemetry pipeline could not frame batch (batch_seq=%d "
                "record_count=%d): %s — batch discarded",
                self._batch_seq,
                record_count,
                exc,
            )
            self.counters.framing_error_count += 1
            self._reset_batch_state()
            return

        try:
            self._link.send(framed)
        except Exception as exc:  # noqa: BLE001 -- the live path is lossy by
            # design; a transmit failure must never propagate into the
            # capture or archive path (T-01-26).
            logger.warning(
                "telemetry pipeline link send failed (batch_seq=%d "
                "record_count=%d bytes=%d): %s",
                self._batch_seq,
                record_count,
                len(framed),
                exc,
            )
            self.counters.link_send_failure_count += 1
        else:
            self.counters.batches_sent += 1
            self.counters.bytes_sent += len(framed)

        self._reset_batch_state()

    def _reset_batch_state(self) -> None:
        self._batch_records = []
        self._batch_base_timestamp_us = None
        self._batch_seq = (self._batch_seq + 1) % _BATCH_SEQ_MODULUS
