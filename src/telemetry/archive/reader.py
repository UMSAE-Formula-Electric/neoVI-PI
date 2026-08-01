"""
telemetry.archive.reader -- the one supported way to read back a session
archive that may have crashed mid-write (ARCH-02), built directly on
`01-RESEARCH.md` Pattern 2's empirically verified finding.

Both of `mcap` 1.4.0's obvious read paths are wrong for a footer-less
(crashed) file, and this file exists specifically to prevent a later
contributor from "simplifying" back to either one:

- `mcap.reader.make_reader()` picks `SeekingReader` for any seekable
  stream, which unconditionally seeks to where the footer *should* be and
  tries to parse whatever bytes are actually there as a `Footer` record.
  On a crashed file that raises a nonsense `RecordLengthLimitExceeded`
  error with an absurd record length -- not a clean "no footer" signal.
- `NonSeekingReader(f).iter_messages()`'s own default,
  `log_time_order=True`, sorts messages before yielding any of them, which
  means it must fully drain the underlying generator into memory first.
  On a real, complete, uncorrupted 50-record crashed file (chunking
  disabled, every record on the stream, only `finish()` never called) this
  recovers *zero of fifty* messages, silently, because the drain-to-sort
  raises before a single message is ever yielded -- not because anything
  is actually missing.

The only configuration verified to recover pre-crash data is
`NonSeekingReader(f).iter_messages(log_time_order=False)`, iterated in a
`for` loop that accumulates results as they arrive and catches both
`mcap.exceptions.EndOfFile` (a clean end between two records) and a bare
`struct.error` (a truncation inside a record header) -- `struct.error` is
not an `mcap` exception type, so an `mcap`-only `except` clause will not
catch it. Everything accumulated before either exception fires is already
recovered and belongs to the caller; it must never be discarded.
`tests/test_archive_crash_recovery.py` pins both failing paths above with
its own test so this file cannot regress unnoticed.
"""

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from mcap.exceptions import EndOfFile
from mcap.reader import NonSeekingReader

from telemetry.archive.record import unpack_frame
from telemetry.archive.session import DONE_FILENAME
from telemetry.wire.frame_source import RawFrame

# The exact set of exceptions the read loop below must tolerate -- a clean
# end-of-stream between two records raises `EndOfFile`; a truncation that
# lands inside a record's own length/header fields raises a bare
# `struct.error`, which is not an `mcap` exception type at all and would
# escape an `except mcap.exceptions.EndOfFile` clause on its own.
_RECOVERABLE_READ_ERRORS = (EndOfFile, struct.error)


@dataclass(frozen=True)
class RecoveredSession:
    """The result of `recover_session`: every `(channel_topic, RawFrame)`
    pair recovered before the read stopped, how many that is, and whether
    the read ended early (a footer-less/crashed file) rather than reaching
    a real, well-formed end of stream."""

    records: Tuple[Tuple[str, RawFrame], ...]
    record_count: int
    truncated: bool


def recover_session(mcap_path) -> RecoveredSession:
    """Read `mcap_path` back through the one supported recovery path.

    Works identically whether the file was closed normally (`finish()`
    called, footer present) or crashed mid-write (no footer, possibly
    truncated mid-record): every complete record written before the file
    ends is returned, in the order it was written, and truncation status
    is reported rather than hidden. A record cut off mid-body is dropped,
    never emitted partially -- `struct.error`/`EndOfFile` firing while
    accumulating a given tuple means that tuple was never appended.
    """
    recovered = []
    truncated = False
    with open(mcap_path, "rb") as f:
        reader = NonSeekingReader(f)
        try:
            for schema, channel, message in reader.iter_messages(log_time_order=False):
                frame = unpack_frame(message.data, message.log_time)
                recovered.append((channel.topic, frame))
        except _RECOVERABLE_READ_ERRORS:
            truncated = True

    return RecoveredSession(
        records=tuple(recovered),
        record_count=len(recovered),
        truncated=truncated,
    )


def is_session_complete(session_dir, done_marker_filename: str = DONE_FILENAME) -> bool:
    """True if `session_dir` carries its `.done` marker -- the single
    predicate Phase 8's SYNC-02 needs to avoid ever copying a session that
    is still mid-write. Defined beside `recover_session` rather than
    re-implemented at each call site."""
    return (Path(session_dir) / done_marker_filename).exists()
