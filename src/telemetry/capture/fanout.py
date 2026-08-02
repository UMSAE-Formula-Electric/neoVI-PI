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

CAP-06 (this plan, 01-07): a frame that passes the allowlist filter can
still be un-encodable for the telemetry path — its id may be absent from
the ID dictionary, or its payload may exceed the CAN DLC maximum. Both are
checked here, before the frame ever reaches the telemetry deque, so a
downstream encode failure never happens silently and never costs CPU on a
frame that would just be thrown away later. This is a pre-flight check,
not the CFR encode itself (`telemetry.wire.encoder.Encoder` still runs
downstream, unchanged, per `01-CONTEXT.md`'s "allowlist... applied here,
before the encoder"). Every failure is caught by its specific named type,
counted on `FanOutCounters`, and logged with the frame's channel, id, and
timestamp — the first occurrence per `(frame_id, is_extended)` in full
detail, repeats counted but not re-logged, so a persistently unknown id
cannot flood the log at bus rate (T-01-18). The archive enqueue above
always happens first and unconditionally, so a telemetry-side failure
never costs the archive a frame — the durability guarantee does not
depend on a frame being encodable.

Threading note: `FanOutCounters` is written only by the capture thread
that calls `submit()` and is read by other threads only after that
capture thread has stopped (e.g. after `join()`), so no lock guards it —
single-item `deque.append()` and `Queue.put_nowait()` are each
individually safe under the GIL, and there is no read-modify-write across
threads while capture is running.

One field is the deliberate exception: `archive_high_water_mark` is a
read-modify-write (`max(current, qsize())`) performed from *two* threads
for the entire duration of a session — this module's capture thread via
`submit()`, and `telemetry.archive.runner.ArchiveRunner`'s consumer thread
via its own `_record_high_water_mark()`, both against the same shared
`FanOutCounters` instance. A bare `max()`-then-assign there is a classic
race (one thread's larger write can be clobbered by the other's stale
read), so that single field is guarded by `FanOutCounters._archive_hwm_lock`
— every other field keeps the lock-free, single-writer discipline above.
"""

import logging
import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, FrozenSet, NamedTuple, Optional, Tuple

from telemetry.wire.dictionary import IdDictionary, UnknownFrameId
from telemetry.wire.encoder import MAX_PAYLOAD_BYTES, PayloadTooLong
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
    marks, throughput accounting, and the telemetry discard/filter counts —
    each counted separately so the live path's loss rate is a set of exact
    numbers, never an inference. `archive_write_failure` is set by
    `telemetry.archive.runner.ArchiveRunner` (not by this module — this
    dataclass is a plain data holder with no dependency on the archive
    package in either direction), the durability-side counterpart to
    `archive_overflow` below."""

    # Throughput accounting.
    frames_submitted: int = 0
    archive_enqueued: int = 0
    telemetry_enqueued: int = 0

    # Archive side (CAP-03: never drops; a full queue is fatal).
    archive_high_water_mark: int = 0
    archive_overflow: bool = False
    archive_write_failure: bool = False

    # Telemetry side (CAP-05: exact discard/filter accounting).
    telemetry_high_water_mark: int = 0
    telemetry_discard_count: int = 0  # dropped by drop-oldest overflow
    telemetry_filtered_count: int = 0  # not on the allowlist — not a discard

    # Telemetry-path encode-precheck failures (CAP-06).
    telemetry_unknown_id_count: int = 0
    telemetry_payload_too_long_count: int = 0
    telemetry_unexpected_error_count: int = 0
    # Per-frame-id log rate limiting (T-01-18): every suppressed repeat is
    # still counted here, so nothing is actually lost even though it isn't
    # re-logged.
    telemetry_error_log_suppressed_count: int = 0

    # Guards ONLY `archive_high_water_mark` -- see the module docstring's
    # threading note. Excluded from `repr`/`==` so this stays a plain data
    # holder everywhere else (log lines, tests) as before.
    _archive_hwm_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )


class FanOut:
    """One capture step's fan-out to two independent consumers."""

    def __init__(
        self,
        archive_maxsize: int,
        telemetry_maxsize: int,
        telemetry_allowlist: FrozenSet[AllowlistKey],
        stop_event: threading.Event,
        dictionary: Optional[IdDictionary] = None,
    ) -> None:
        self.archive_queue: "queue.Queue[CapturedFrame]" = queue.Queue(maxsize=archive_maxsize)
        self.telemetry_queue: Deque[CapturedFrame] = deque(maxlen=telemetry_maxsize)
        self.telemetry_allowlist = telemetry_allowlist
        self.stop_event = stop_event
        # Optional: when absent, the unknown-id half of the CAP-06 precheck
        # is skipped (the payload-length half needs no dictionary and
        # always runs). Callers that construct a FanOut without a
        # dictionary -- e.g. tests exercising only the archive side, or
        # 01-04's tracer -- keep their existing behavior unchanged.
        self.dictionary = dictionary
        self.counters = FanOutCounters()
        self._logged_error_frame_keys: set = set()

    def submit(self, captured: CapturedFrame) -> None:
        """Fan `captured` out to the archive queue (never-drop, fatal if
        full) and, if allowlisted, the telemetry deque (drop-oldest).
        Neither branch can block or be blocked by the other, and this call
        never raises `queue.Full` to the caller."""
        self.counters.frames_submitted += 1

        try:
            self.archive_queue.put_nowait(captured)
        except queue.Full:
            logger.critical(
                "archive queue full — durability guarantee at risk; "
                "stopping session (channel=%s frame_id=0x%X is_extended=%s "
                "timestamp_us=%d)",
                captured.channel,
                captured.frame.frame_id,
                captured.frame.is_extended,
                captured.frame.timestamp_us,
            )
            self.counters.archive_overflow = True
            self.stop_event.set()
            return

        self.counters.archive_enqueued += 1
        with self.counters._archive_hwm_lock:
            self.counters.archive_high_water_mark = max(
                self.counters.archive_high_water_mark, self.archive_queue.qsize()
            )

        key: AllowlistKey = (captured.frame.frame_id, captured.frame.is_extended)
        if key not in self.telemetry_allowlist:
            self.counters.telemetry_filtered_count += 1
            return

        if not self._passes_telemetry_precheck(captured):
            return

        was_full = len(self.telemetry_queue) == self.telemetry_queue.maxlen
        self.telemetry_queue.append(captured)
        if was_full:
            self.counters.telemetry_discard_count += 1
        self.counters.telemetry_enqueued += 1
        self.counters.telemetry_high_water_mark = max(
            self.counters.telemetry_high_water_mark, len(self.telemetry_queue)
        )

    def _passes_telemetry_precheck(self, captured: CapturedFrame) -> bool:
        """CAP-06: catches every reason `captured` cannot be carried on the
        telemetry path, counts it on a specific `FanOutCounters` field, and
        logs it (rate-limited per frame id) — never silently swallowed and
        never left to surface as an unhandled exception out of `submit`.
        The archive enqueue in `submit` above has already happened
        unconditionally by the time this runs, so a `False` return here
        never costs the archive a frame."""
        frame = captured.frame
        try:
            if len(frame.payload) > MAX_PAYLOAD_BYTES:
                raise PayloadTooLong(
                    f"frame_id=0x{frame.frame_id:X} payload length "
                    f"{len(frame.payload)} exceeds the {MAX_PAYLOAD_BYTES}-byte "
                    f"CAN DLC maximum"
                )
            if self.dictionary is not None:
                self.dictionary.index_of(frame.frame_id, frame.is_extended)
        except UnknownFrameId as exc:
            self._record_telemetry_error(captured, "telemetry_unknown_id_count", exc)
            return False
        except PayloadTooLong as exc:
            self._record_telemetry_error(captured, "telemetry_payload_too_long_count", exc)
            return False
        except Exception as exc:  # noqa: BLE001 -- last-resort net: always
            # counted and logged below with full frame context, never
            # silently swallowed and never left to propagate out of
            # submit(). This is deliberately unlike src/new_logger.py's
            # `except Exception: debug(...)` (invisible unless a module
            # flag is set) — CAP-06 exists specifically to eliminate that.
            self._record_telemetry_error(captured, "telemetry_unexpected_error_count", exc)
            return False
        return True

    def _record_telemetry_error(
        self, captured: CapturedFrame, counter_name: str, exc: Exception
    ) -> None:
        setattr(self.counters, counter_name, getattr(self.counters, counter_name) + 1)

        frame = captured.frame
        error_key: AllowlistKey = (frame.frame_id, frame.is_extended)
        if error_key in self._logged_error_frame_keys:
            self.counters.telemetry_error_log_suppressed_count += 1
            return
        self._logged_error_frame_keys.add(error_key)

        logger.warning(
            "telemetry path cannot carry frame (channel=%s frame_id=0x%X "
            "is_extended=%s timestamp_us=%d): %s — archive path unaffected; "
            "further occurrences of this frame id are counted, not re-logged",
            captured.channel,
            frame.frame_id,
            frame.is_extended,
            frame.timestamp_us,
            exc,
        )
