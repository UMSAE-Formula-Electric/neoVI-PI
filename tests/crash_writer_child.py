"""
tests/crash_writer_child.py -- standalone subprocess helper for the
kill-based proxy test in `tests/test_archive_crash_recovery.py`.

Builds a real session through `new_session`, writes synthetic frames
through the real `ArchiveWriter`, and prints one confirmation line to
stdout -- flushed immediately -- every time a flush-and-fsync cycle
completes, naming the cumulative record count at that point. The parent
test reads those lines until it has seen enough confirmations, then kills
this process outright. This script never calls `mark_done`: the whole
point is that a killed session has no `.done` marker.

Protocol (one line per event, all flushed immediately):
    SESSION_DIR:<path>   -- printed once, right after the session directory
                             is created, so the parent (which does not
                             control the UTC/counter-derived session name)
                             knows exactly which directory to inspect.
    FSYNC:<record_count>  -- printed every time ArchiveWriter's internal
                             flush-and-fsync cadence fires, naming the
                             cumulative number of records added so far.
"""

import argparse
import struct
import time

from telemetry.archive.session import new_session
from telemetry.archive.writer import ArchiveWriter
from telemetry.wire.frame_source import RawFrame

_FRAME_ID = 0x100
_PAYLOAD_STRUCT = struct.Struct("<I")  # payload encodes the record's own index


def _build_frame(index: int) -> RawFrame:
    return RawFrame(
        timestamp_us=index,
        frame_id=_FRAME_ID,
        is_extended=False,
        payload=_PAYLOAD_STRUCT.pack(index),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="archive root passed to new_session")
    parser.add_argument("--record-count", type=int, required=True)
    parser.add_argument("--flush-every-records", type=int, required=True)
    parser.add_argument("--flush-every-s", type=float, default=60.0)
    parser.add_argument("--channel-name", default="MAIN")
    args = parser.parse_args()

    session = new_session(args.output_dir)
    print(f"SESSION_DIR:{session.directory}", flush=True)

    writer = ArchiveWriter(
        session.mcap_path,
        channel_names=[args.channel_name],
        flush_every_records=args.flush_every_records,
        flush_every_s=args.flush_every_s,
    )

    for index in range(args.record_count):
        writer.add(args.channel_name, _build_frame(index))
        # ArchiveWriter offers no public event for "a flush-and-fsync cycle
        # just completed" -- this script exists solely to drive this one
        # test, so it reaches into `_records_since_flush` (reset to 0
        # exactly when a flush-and-fsync cycle completes inside `add()`)
        # rather than approximating the cadence from record counts and
        # timing alone.
        if writer._records_since_flush == 0:
            print(f"FSYNC:{writer._sequence}", flush=True)

    # Deliberately never call writer.close() or mark_done(): a killed
    # session must be found with no .done marker. Idle so the parent has
    # unbounded time to send the kill after reading its confirmations.
    while True:
        time.sleep(1.0)


if __name__ == "__main__":
    main()
