"""
telemetry.archive.writer — `ArchiveWriter`, built directly on
`01-RESEARCH.md` Pattern 2's verified reference implementation (ARCH-01,
ARCH-04). Every fact below was verified empirically in the research
session against the installed `mcap==1.4.0`, not read from its
documentation — this project's recorded history is three separate cases of
prose figures disagreeing with measured reality, and this module does not
add a fourth:

1. **Own the file object, never hand `mcap.writer.Writer` a string path.**
   `Writer` never calls `fsync`/`fdatasync` anywhere in its class, and
   `add_message()` doesn't always even reach the stream's `.write()` — the
   caller must own the file descriptor to fsync it at all.

2. **Construct `Writer(file_obj, use_chunking=False)`.** The library's
   default (`use_chunking=True`, `chunk_size=1MiB`) buffers messages purely
   in an in-process `ChunkBuilder` until the chunk reaches 1 MB — at raw-CAN
   record sizes that is tens of thousands of frames sitting nowhere durable
   at all, strictly worse than an unflushed OS buffer, and incompatible with
   the locked record-count-or-time flush cadence: `chunk_size` is a byte
   threshold, and `mcap` exposes no count/time knob to express that cadence.
   `use_chunking=False` makes every `add_message()` call reach
   `stream.write()` immediately — verified empirically this session (a
   single record written with `flush_every_records=1` produces a non-zero
   file readable via `recover_session` while the writer is still open;
   `stream.write()` alone, without the explicit flush this module adds, is
   not itself enough to make bytes visible to another file handle, since
   Python's own `io.BufferedWriter` still holds them until flushed — see
   point 3).

3. **The record-count-or-time fsync cadence is entirely this module's job.**
   `Writer` never calls `flush`/`fsync`/`fdatasync` anywhere in its class —
   after each `add`, this module flushes the file object and calls
   `getattr(os, "fdatasync", os.fsync)` on its descriptor once either
   `flush_every_records` or `flush_every_s` has elapsed, whichever comes
   first. Both trackers reset together on every sync, so a count-triggered
   sync also restarts the elapsed-time window rather than leaving a stale
   clock that could fire redundantly on the very next call. The monotonic
   clock is an injectable callable (`clock=`, defaulting to
   `time.monotonic`) so the time-based branch is testable without sleeping.
   The `getattr` fallback is required for this code to run at all on the
   Windows dev box, where `os.fdatasync` does not exist — the CM4's Linux
   `fdatasync` branch is not exercisable here, and that limit is recorded,
   not hidden; `docs/power-pull-test.md` is where the Linux branch is
   actually proven. Neither `flush()` nor the sync call is ever wrapped in
   `try`/`except` — an I/O failure on the durability path must stop the
   session loudly, not be swallowed into a healthy-looking log line.

`records_written`, `flush_count`, and `is_closed` are read-only properties:
the first two make the cadence's own bookkeeping directly inspectable
(tests assert they agree with the observed sync/record counts), and
`is_closed` becomes `True` only after `close()`'s `finish()`, final flush,
and final sync have all returned — `close()` always performs that final
sync regardless of how many records are pending, by routing through the
exact same `_flush_and_sync()` cadence helper `add()` uses, so
`flush_count` accounts for it too. That makes
`telemetry.archive.session.mark_done`'s "only after close-and-flush
returns" precondition (ARCH-05) structural, not a calling convention
someone can forget.
"""

import logging
import os
import time
from pathlib import Path
from typing import Callable, Dict, Iterable

from mcap.writer import Writer

from telemetry.archive.record import pack_frame
from telemetry.wire.frame_source import RawFrame

logger = logging.getLogger(__name__)

# `encoding=""` in mcap's own register_schema docstring means "no schema
# available" for this channel; when encoding is empty, `data` must be
# zero-length. Every channel this writer registers shares the same
# archive/record.py on-disk layout, so one shared, schema-less registration
# is correct — there is nothing a formal schema encoding would add here.
_SCHEMA_NAME = "telemetry.archive.record.RawFrame"
_MESSAGE_ENCODING = "application/x-telemetry-rawframe"


class ArchiveWriter:
    """Owns one session's `.mcap` file: registers one schema and one
    channel per configured channel name (topic `/can/{channel_name}`), and
    writes/flushes/fsyncs every archived frame on the locked cadence."""

    def __init__(
        self,
        path,
        channel_names: Iterable[str],
        flush_every_records: int = 1000,
        flush_every_s: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = Path(path)
        self._f = open(self._path, "wb")  # own the file object — never a string path
        self._writer = Writer(self._f, use_chunking=False)
        self._writer.start()

        schema_id = self._writer.register_schema(name=_SCHEMA_NAME, encoding="", data=b"")
        self._channel_ids: Dict[str, int] = {
            name: self._writer.register_channel(
                topic=f"/can/{name}",
                message_encoding=_MESSAGE_ENCODING,
                schema_id=schema_id,
            )
            for name in channel_names
        }

        self._flush_every_records = flush_every_records
        self._flush_every_s = flush_every_s
        self._clock = clock
        self._records_since_flush = 0
        self._last_flush_t = self._clock()
        self._sequence = 0
        self._records_written = 0
        self._flush_count = 0
        # Linux (the CM4 target): os.fdatasync. Windows dev box (verified
        # this session to lack os.fdatasync entirely): falls back to
        # os.fsync, which the dev-laptop test suite exercises instead.
        self._fsync = getattr(os, "fdatasync", os.fsync)
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """True only after `close()`'s `finish()` + flush + fsync have all
        returned. `telemetry.archive.session.mark_done` requires this to be
        true before it will write the `.done` marker."""
        return self._closed

    @property
    def records_written(self) -> int:
        """Total records handed to `add()` and accepted so far (lifetime
        count, never reset by a flush)."""
        return self._records_written

    @property
    def flush_count(self) -> int:
        """How many times `_flush_and_sync()` has run — one per
        count-or-time cadence trigger during `add()`, plus exactly one more
        from `close()`'s unconditional final sync."""
        return self._flush_count

    def add(self, channel_name: str, frame: RawFrame) -> None:
        """Write one raw frame to `channel_name`'s MCAP channel, flushing
        and fsyncing when the configured record-count-or-time cadence has
        elapsed."""
        if self._closed:
            raise RuntimeError("cannot add() to an ArchiveWriter after close()")
        try:
            channel_id = self._channel_ids[channel_name]
        except KeyError:
            raise KeyError(
                f"channel {channel_name!r} was not registered at construction "
                f"time (known channels: {sorted(self._channel_ids)})"
            ) from None

        data = pack_frame(frame)
        log_time_ns = frame.timestamp_us * 1000
        self._writer.add_message(
            channel_id,
            log_time_ns,
            data,
            log_time_ns,
            self._sequence,
        )
        self._sequence += 1
        self._records_since_flush += 1
        self._records_written += 1

        now = self._clock()
        if (
            self._records_since_flush >= self._flush_every_records
            or now - self._last_flush_t >= self._flush_every_s
        ):
            self._flush_and_sync()

    def _flush_and_sync(self) -> None:
        """Flush the file object and fsync its descriptor, then reset both
        cadence trackers together — a count-triggered sync also restarts
        the elapsed-time window, so it can never fire again redundantly for
        time already accounted for by this sync. Never wrapped in
        `try`/`except`: a failure here must stop the session loudly."""
        self._f.flush()
        self._fsync(self._f.fileno())
        self._records_since_flush = 0
        self._last_flush_t = self._clock()
        self._flush_count += 1

    def close(self) -> None:
        """Idempotent. `finish()` writes DataEnd/summary/Footer/magic, then
        an unconditional final sync through the same cadence helper `add()`
        uses (so `flush_count` accounts for it too, regardless of how many
        records were pending), then closes the file. Sets `is_closed`."""
        if self._closed:
            return
        self._writer.finish()
        self._flush_and_sync()
        self._f.close()
        self._closed = True
        logger.info("archive writer closed: %s", self._path)
