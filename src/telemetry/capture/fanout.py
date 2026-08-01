"""
telemetry.capture.fanout — the architectural centre of Phase 1
(CAP-01..06), built on `01-RESEARCH.md` Pattern 1's verified fan-out shape
(already locked in `01-CONTEXT.md`, restated here as the real
implementation).

`FanOut.submit` is the single point where the archive queue and the
telemetry deque diverge; the telemetry side holds no handle that can block
the archive side (CAP-04's structural guarantee). It does exactly two
things, neither of which can block:

- `put_nowait` onto the bounded archive `queue.Queue`. A full archive queue
  is **fatal** by locked decision (CAP-03: the archive consumer never
  drops) — logs at critical severity, sets the overflow flag, sets the
  stop event, and returns. An unbounded queue would only relocate the
  failure to an OOM kill; a loud, structural stop is the honest failure
  mode.
- If and only if the frame's `(frame_id, is_extended)` key is in the
  telemetry allowlist, append to the bounded `collections.deque`. The
  allowlist filter lives here, upstream of the CFR encoder, because
  filtering before encoding saves CPU and queue pressure as well as
  bandwidth, rather than paying to encode frames that are then thrown away.

`deque(maxlen=N).append()` gives no signal that it evicted anything, so
CAP-05's discard-counting requirement is implemented by checking fullness
**before** the append, never by inspecting the deque afterward.
"""

import logging
import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, FrozenSet, NamedTuple, Tuple

from telemetry.wire.frame_source import RawFrame

logger = logging.getLogger(__name__)

AllowlistKey = Tuple[int, bool]  # (frame_id, is_extended)


class CapturedFrame(NamedTuple):
    """A raw frame plus the channel (bus) it was captured on — carries the
    bus without modifying the frozen `RawFrame` contract."""

    channel: str
    frame: RawFrame


@dataclass
class FanOutCounters:
    """Mutable, shared counters (CAP-05/CAP-06): both queues' high-water
    marks, the telemetry discard count, and whether the archive queue has
    ever overflowed. `archive_write_failure` is set by
    `telemetry.archive.runner.ArchiveRunner` (not by this module — this
    dataclass is a plain data holder with no dependency on the archive
    package in either direction) when the archive writer itself raises,
    the durability-side counterpart to `archive_overflow` above."""

    archive_high_water_mark: int = 0
    telemetry_high_water_mark: int = 0
    telemetry_discard_count: int = 0
    archive_overflow: bool = False
    archive_write_failure: bool = False


class FanOut:
    """One capture step's fan-out to two independent consumers."""

    def __init__(
        self,
        archive_maxsize: int,
        telemetry_maxsize: int,
        telemetry_allowlist: FrozenSet[AllowlistKey],
        stop_event: threading.Event,
    ) -> None:
        self.archive_queue: "queue.Queue[CapturedFrame]" = queue.Queue(maxsize=archive_maxsize)
        self.telemetry_queue: Deque[CapturedFrame] = deque(maxlen=telemetry_maxsize)
        self.telemetry_allowlist = telemetry_allowlist
        self.stop_event = stop_event
        self.counters = FanOutCounters()

    def submit(self, captured: CapturedFrame) -> None:
        """Fan `captured` out to the archive queue (never-drop, fatal if
        full) and, if allowlisted, the telemetry deque (drop-oldest).
        Neither branch can block or be blocked by the other."""
        try:
            self.archive_queue.put_nowait(captured)
        except queue.Full:
            logger.critical(
                "archive queue full — durability guarantee at risk; "
                "stopping session (channel=%s frame_id=0x%X is_extended=%s)",
                captured.channel,
                captured.frame.frame_id,
                captured.frame.is_extended,
            )
            self.counters.archive_overflow = True
            self.stop_event.set()
            return

        self.counters.archive_high_water_mark = max(
            self.counters.archive_high_water_mark, self.archive_queue.qsize()
        )

        key: AllowlistKey = (captured.frame.frame_id, captured.frame.is_extended)
        if key not in self.telemetry_allowlist:
            return

        was_full = len(self.telemetry_queue) == self.telemetry_queue.maxlen
        self.telemetry_queue.append(captured)
        if was_full:
            self.counters.telemetry_discard_count += 1
        self.counters.telemetry_high_water_mark = max(
            self.counters.telemetry_high_water_mark, len(self.telemetry_queue)
        )
