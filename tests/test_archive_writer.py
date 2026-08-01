"""
Requirements covered: ARCH-01, ARCH-04, CAP-03.

Task 1 asserts the archive writer's durability contract directly, not by
inspecting its source: every written frame round-trips through
`recover_session` (ARCH-01), the count-or-time fsync cadence is provably
invoked exactly on schedule with no redundant same-window sync (ARCH-04),
a single record reaches the OS-visible file before `close()` (the
mcap-default-chunking regression guard), and a raising sync propagates
rather than being swallowed.

Task 2 asserts `ArchiveRunner`, the consumer end of `FanOut.archive_queue`:
every submitted frame is drained into the archive with none missing or
duplicated (CAP-03's never-drop half, proven through the real consumer), a
deliberately slow sync never shows up as latency on the producer's own
`FanOut.submit()` calls (ARCH-04's real claim), and shutdown -- by sentinel
or by stop event -- always drains rather than discards.
"""

import queue
import threading
import time
from collections import Counter

import pytest

from telemetry.archive.reader import recover_session
from telemetry.archive.runner import STOP, ArchiveRunner
from telemetry.archive.writer import ArchiveWriter
from telemetry.capture.fanout import CapturedFrame, FanOut, FanOutCounters
from telemetry.wire.frame_source import RawFrame

CHANNEL_A = "MAIN"
CHANNEL_B = "SENSOR"


def _make_frame(index: int) -> RawFrame:
    """A frame whose id/extended-flag/payload/timestamp all vary with
    `index`, so a round-trip test can catch a field being dropped or two
    records being swapped, not just a count matching by coincidence."""
    return RawFrame(
        timestamp_us=index * 1000,
        frame_id=0x100 + index,
        is_extended=bool(index % 3 == 0),
        payload=bytes([index % 256]) * ((index % 8) + 1),
    )


class _FakeClock:
    """An injectable monotonic clock a test can advance without sleeping,
    per Task 1's action text ('the monotonic clock as an injectable
    callable so the time branch is testable without sleeping')."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, delta: float) -> None:
        self.value += delta


# ---------------------------------------------------------------------------
# Task 1: cadence, sync accounting, and the unchunked-write pin
# ---------------------------------------------------------------------------


def test_two_hundred_frames_across_two_channels_round_trip(tmp_path):
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(path, channel_names=[CHANNEL_A, CHANNEL_B])

    expected = []
    for i in range(200):
        channel = CHANNEL_A if i % 2 == 0 else CHANNEL_B
        frame = _make_frame(i)
        writer.add(channel, frame)
        expected.append((f"/can/{channel}", frame))
    writer.close()

    recovered = recover_session(path)

    assert recovered.record_count == 200
    assert not recovered.truncated
    # Multiset equality: every recovered (topic, frame) pair -- id, extended
    # flag, payload, and timestamp all included in the NamedTuple -- matches
    # exactly one written pair, with none missing and none duplicated; a
    # frame's topic matching the channel it was submitted on is asserted by
    # this same comparison, since the pair is only equal if both are.
    assert Counter(recovered.records) == Counter(expected)
    assert {topic for topic, _ in recovered.records} == {
        f"/can/{CHANNEL_A}",
        f"/can/{CHANNEL_B}",
    }


def test_count_cadence_produces_exactly_the_configured_sync_count(tmp_path):
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(
        path,
        channel_names=[CHANNEL_A],
        flush_every_records=10,
        flush_every_s=1000.0,  # never fires on its own in this test
    )
    sync_calls = []
    writer._fsync = lambda fd: sync_calls.append(fd)

    for i in range(100):
        writer.add(CHANNEL_A, _make_frame(i))

    assert len(sync_calls) == 10
    assert writer.flush_count == 10
    assert writer.records_written == 100

    writer.close()

    # close() always performs one more, unconditional sync.
    assert len(sync_calls) == 11
    assert writer.flush_count == 11


def test_time_cadence_fires_once_per_elapsed_window(tmp_path):
    clock = _FakeClock(start=0.0)
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(
        path,
        channel_names=[CHANNEL_A],
        flush_every_records=1_000_000,  # never fires on its own in this test
        flush_every_s=0.25,
        clock=clock,
    )
    sync_calls = []
    writer._fsync = lambda fd: sync_calls.append(fd)

    writer.add(CHANNEL_A, _make_frame(0))
    assert len(sync_calls) == 0  # no time has elapsed yet

    clock.advance(0.3)
    writer.add(CHANNEL_A, _make_frame(1))
    assert len(sync_calls) == 1

    clock.advance(0.3)
    writer.add(CHANNEL_A, _make_frame(2))
    assert len(sync_calls) == 2

    writer.close()
    assert len(sync_calls) == 3


def test_count_trigger_resets_the_elapsed_window_no_redundant_time_sync(tmp_path):
    """The count trigger firing first must not also produce a redundant
    time-triggered sync in the same window -- the elapsed timer resets on
    every sync, count-triggered or not."""
    clock = _FakeClock(start=0.0)
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(
        path,
        channel_names=[CHANNEL_A],
        flush_every_records=5,
        flush_every_s=1.0,
        clock=clock,
    )
    sync_calls = []
    writer._fsync = lambda fd: sync_calls.append(fd)

    # Advance close to (but under) the time threshold before the count
    # trigger fires on the 5th record.
    clock.advance(0.9)
    for i in range(5):
        writer.add(CHANNEL_A, _make_frame(i))
    assert len(sync_calls) == 1  # the count trigger, at record 5

    # Total elapsed time since t=0 is now 1.1s -- past flush_every_s -- but
    # elapsed time since the reset at t=0.9 is only 0.2s. If the reset had
    # not happened, this record would spuriously trigger a second, redundant
    # time-based sync for a window the count trigger already covered.
    clock.advance(0.2)
    writer.add(CHANNEL_A, _make_frame(5))
    assert len(sync_calls) == 1

    writer.close()
    assert len(sync_calls) == 2  # close()'s own unconditional final sync


def test_close_always_syncs_once_more_regardless_of_pending_records(tmp_path):
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(
        path,
        channel_names=[CHANNEL_A],
        flush_every_records=1000,  # will not be reached by 3 records
        flush_every_s=1000.0,
    )
    sync_calls = []
    writer._fsync = lambda fd: sync_calls.append(fd)

    for i in range(3):
        writer.add(CHANNEL_A, _make_frame(i))
    assert len(sync_calls) == 0  # neither cadence has fired yet

    writer.close()
    assert len(sync_calls) == 1
    assert writer.flush_count == 1
    assert writer.records_written == 3


def test_flush_count_and_records_written_agree_with_observed_counts(tmp_path):
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(
        path,
        channel_names=[CHANNEL_A],
        flush_every_records=7,
        flush_every_s=1000.0,
    )
    sync_calls = []
    writer._fsync = lambda fd: sync_calls.append(fd)

    for i in range(23):
        writer.add(CHANNEL_A, _make_frame(i))

    assert writer.records_written == 23
    assert writer.flush_count == len(sync_calls) == 3  # 23 // 7

    writer.close()
    assert writer.flush_count == len(sync_calls) == 4  # + close()'s final sync


def test_one_record_reaches_disk_and_is_readable_before_close(tmp_path):
    """Regression guard for `mcap`'s default chunking: under
    `use_chunking=True` (the library default this writer deliberately
    disables), up to 1 MB of messages sit in an in-process `ChunkBuilder`
    before a single byte reaches the stream -- the file would still be
    effectively empty at this point. `flush_every_records=1` forces the
    cadence to fire on this write so the assertion is about unchunked
    writes reaching the OS-visible file, not about cadence timing (that is
    the other Task 1 tests' job)."""
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(
        path, channel_names=[CHANNEL_A], flush_every_records=1, flush_every_s=1000.0
    )

    frame = _make_frame(0)
    writer.add(CHANNEL_A, frame)

    assert path.stat().st_size > 0

    recovered = recover_session(path)
    assert recovered.record_count == 1
    assert recovered.records[0] == (f"/can/{CHANNEL_A}", frame)

    writer.close()


def test_a_raising_sync_propagates_rather_than_being_swallowed(tmp_path):
    """A silently no-op'd sync is the failure mode that would make every
    other durability claim in this phase false while every other test
    still passed -- `add()` must let a sync failure through."""
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(
        path, channel_names=[CHANNEL_A], flush_every_records=1, flush_every_s=1000.0
    )

    def raising_fsync(fd):
        raise OSError("simulated durability failure")

    writer._fsync = raising_fsync

    with pytest.raises(OSError):
        writer.add(CHANNEL_A, _make_frame(0))

    writer._f.close()  # cleanup only -- writer never reached is_closed


# ---------------------------------------------------------------------------
# Task 2: the archive drain thread and the never-stalls-capture proof
# ---------------------------------------------------------------------------


def test_archive_runner_drains_every_submitted_frame_none_missing_or_duplicated(tmp_path):
    stop_event = threading.Event()
    fan_out = FanOut(
        archive_maxsize=200,
        telemetry_maxsize=10,
        telemetry_allowlist=frozenset(),
        stop_event=stop_event,
    )
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(path, channel_names=[CHANNEL_A, CHANNEL_B])
    runner = ArchiveRunner(fan_out.archive_queue, writer, fan_out.counters, stop_event)
    runner.start()

    frame_count = 150
    expected = []
    for i in range(frame_count):
        channel = CHANNEL_A if i % 2 == 0 else CHANNEL_B
        frame = _make_frame(i)
        fan_out.submit(CapturedFrame(channel=channel, frame=frame))
        expected.append((f"/can/{channel}", frame))

    fan_out.archive_queue.put(STOP)
    runner.join(timeout=10)

    assert not runner.is_alive()
    assert not stop_event.is_set()
    writer.close()

    recovered = recover_session(path)
    assert recovered.record_count == frame_count
    assert Counter(recovered.records) == Counter(expected)


def test_slow_sync_does_not_slow_the_producer_and_every_frame_still_lands(tmp_path):
    """ARCH-04's real claim: the flush cost lands on the queue, not on the
    producer. The writer's sync is patched to sleep far longer than a
    submit() call has any business taking; every individual submit() must
    stay bounded well under that sleep, and every frame must still reach
    the archive once the drain completes."""
    stop_event = threading.Event()
    fan_out = FanOut(
        archive_maxsize=500,
        telemetry_maxsize=10,
        telemetry_allowlist=frozenset(),
        stop_event=stop_event,
    )
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(
        path, channel_names=[CHANNEL_A], flush_every_records=1, flush_every_s=1000.0
    )

    sync_sleep_s = 0.05

    def slow_fsync(fd):
        time.sleep(sync_sleep_s)

    writer._fsync = slow_fsync

    runner = ArchiveRunner(fan_out.archive_queue, writer, fan_out.counters, stop_event)
    runner.start()

    frame_count = 40
    max_submit_duration = 0.0
    expected = []
    for i in range(frame_count):
        frame = _make_frame(i)
        started = time.perf_counter()
        fan_out.submit(CapturedFrame(channel=CHANNEL_A, frame=frame))
        max_submit_duration = max(max_submit_duration, time.perf_counter() - started)
        expected.append((f"/can/{CHANNEL_A}", frame))

    fan_out.archive_queue.put(STOP)
    runner.join(timeout=10)

    assert max_submit_duration < sync_sleep_s / 2, (
        f"a submit() call took {max_submit_duration:.4f}s -- the slow sync's "
        f"{sync_sleep_s}s cost leaked onto the producer's critical path"
    )
    assert not stop_event.is_set()
    writer.close()

    recovered = recover_session(path)
    assert Counter(recovered.records) == Counter(expected)


def test_runner_exits_cleanly_on_sentinel(tmp_path):
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(path, channel_names=[CHANNEL_A])
    archive_queue: "queue.Queue" = queue.Queue()
    counters = FanOutCounters()
    stop_event = threading.Event()

    runner = ArchiveRunner(archive_queue, writer, counters, stop_event)
    runner.start()

    for i in range(3):
        archive_queue.put_nowait(CapturedFrame(channel=CHANNEL_A, frame=_make_frame(i)))
    archive_queue.put_nowait(STOP)

    runner.join(timeout=5)

    assert not runner.is_alive()
    assert not stop_event.is_set()  # a clean sentinel stop never itself sets the stop event
    writer.close()

    recovered = recover_session(path)
    assert recovered.record_count == 3


def test_runner_exits_on_stop_event_and_drains_remaining_items(tmp_path):
    """A stop request must never discard frames already sitting in the
    queue -- the stop event is set before the runner ever starts draining,
    and every already-queued item must still land in the archive."""
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(path, channel_names=[CHANNEL_A])
    archive_queue: "queue.Queue" = queue.Queue()
    counters = FanOutCounters()
    stop_event = threading.Event()

    pending = [CapturedFrame(channel=CHANNEL_A, frame=_make_frame(i)) for i in range(5)]
    for item in pending:
        archive_queue.put_nowait(item)
    stop_event.set()

    runner = ArchiveRunner(archive_queue, writer, counters, stop_event)
    runner.start()
    runner.join(timeout=5)

    assert not runner.is_alive()
    assert archive_queue.empty()
    writer.close()

    recovered = recover_session(path)
    assert recovered.record_count == 5


def test_high_water_mark_recorded_on_shared_counters_after_join(tmp_path):
    path = tmp_path / "session.mcap"
    writer = ArchiveWriter(path, channel_names=[CHANNEL_A])
    archive_queue: "queue.Queue" = queue.Queue()
    counters = FanOutCounters()
    stop_event = threading.Event()

    assert counters.archive_high_water_mark == 0

    for i in range(10):
        archive_queue.put_nowait(CapturedFrame(channel=CHANNEL_A, frame=_make_frame(i)))
    archive_queue.put_nowait(STOP)

    runner = ArchiveRunner(archive_queue, writer, counters, stop_event)
    runner.start()
    runner.join(timeout=5)

    assert counters.archive_high_water_mark > 0
    writer.close()
