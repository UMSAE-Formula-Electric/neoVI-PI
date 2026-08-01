"""
telemetry.archive.runner — `ArchiveRunner`, the consumer end of
`FanOut.archive_queue` (ARCH-04, CAP-03), built on the thread discipline
`01-PATTERNS.md` extracts from `src/new_logger.py`'s `capture_thread`/
`writer_thread` pair: name the thread for debugging, poll a shared
`threading.Event` every loop iteration rather than blocking forever, use a
module-level sentinel pushed onto the queue to signal drain-and-stop, and
keep this thread non-daemon (mirroring `new_logger.py`'s `t_writer`) so it
finishes flushing before the process exits — the capture thread is the
daemon, the writer never is.

This is the one and only place `telemetry.archive` depends on
`telemetry.capture` (for `CapturedFrame`); `telemetry.capture.fanout` never
imports anything from `telemetry.archive` in return. That one-directional
dependency is what makes ARCH-04's "flushing never stalls capture" and
CAP-04's "the telemetry consumer cannot backpressure the archive path"
structural facts rather than promises: the producer (`FanOut.submit`) holds
a queue and nothing else, and has no way to reach into, block on, or even
know about the writer that eventually drains it.

Durability failures are not swallowed. Unlike `new_logger.py`'s
`capture_thread`, which catches a bare `Exception`, reports it only through
a debug helper invisible unless a module flag is set, and then exits
quietly, a write failure here is logged at critical severity with the
frame's channel, id, and timestamp, recorded on the shared `FanOutCounters`
object (`archive_write_failure`), and re-raised after the stop event is
set — so a durability failure stops the session visibly rather than
continuing to accept frames it is no longer persisting.
"""

import logging
import queue
import threading
from typing import Optional

from telemetry.archive.writer import ArchiveWriter
from telemetry.capture.fanout import CapturedFrame, FanOutCounters

logger = logging.getLogger(__name__)

# Pushed onto `FanOut.archive_queue` by a caller (or a test) to tell the
# runner to drain whatever remains and stop. Public (not `_STOP` as in
# `new_logger.py`) because, unlike that module's producer/consumer pair
# living in one file, here the producer of this sentinel (the CLI, or a
# test) lives in a different module than the runner that consumes it.
STOP = object()

_DEFAULT_POLL_TIMEOUT_S = 0.1
_DEFAULT_THREAD_NAME = "archive-writer"


class ArchiveRunner:
    """Drains `archive_queue` into `writer.add()` on its own non-daemon
    thread. Neither a slow flush nor a slow sync inside `writer.add()` can
    ever be observed by whoever is calling `FanOut.submit()` — that cost
    lands entirely on this thread and the queue between them."""

    def __init__(
        self,
        archive_queue: "queue.Queue[CapturedFrame]",
        writer: ArchiveWriter,
        counters: FanOutCounters,
        stop_event: threading.Event,
        poll_timeout_s: float = _DEFAULT_POLL_TIMEOUT_S,
        name: str = _DEFAULT_THREAD_NAME,
    ) -> None:
        self._archive_queue = archive_queue
        self._writer = writer
        self._counters = counters
        self._stop_event = stop_event
        self._poll_timeout_s = poll_timeout_s
        self.thread = threading.Thread(target=self._run, name=name, daemon=False)

    def start(self) -> None:
        self.thread.start()

    def join(self, timeout: Optional[float] = None) -> None:
        self.thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._archive_queue.get(timeout=self._poll_timeout_s)
            except queue.Empty:
                continue

            self._record_high_water_mark()
            if item is STOP:
                break
            self._write(item)

        # Stopping (sentinel or stop_event) must never discard frames that
        # are already sitting in the queue — drain the rest before
        # returning, exactly as `new_logger.py`'s writer_thread drains
        # raw_queue down to its own _STOP rather than exiting early.
        self._drain_remaining()

    def _drain_remaining(self) -> None:
        while True:
            try:
                item = self._archive_queue.get_nowait()
            except queue.Empty:
                return
            if item is STOP:
                continue
            self._record_high_water_mark()
            self._write(item)

    def _record_high_water_mark(self) -> None:
        self._counters.archive_high_water_mark = max(
            self._counters.archive_high_water_mark, self._archive_queue.qsize()
        )

    def _write(self, captured: CapturedFrame) -> None:
        try:
            self._writer.add(captured.channel, captured.frame)
        except Exception:
            logger.critical(
                "archive write failed -- durability guarantee broken; stopping "
                "session (channel=%s frame_id=0x%X is_extended=%s timestamp_us=%s)",
                captured.channel,
                captured.frame.frame_id,
                captured.frame.is_extended,
                captured.frame.timestamp_us,
            )
            self._counters.archive_write_failure = True
            self._stop_event.set()
            raise
