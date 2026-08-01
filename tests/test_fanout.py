"""
Requirements covered: CAP-01, CAP-03, CAP-04, CAP-05, CAP-06.

Task 1 proves the divergent overflow policies (CAP-03), exact discard/
filter/high-water-mark accounting (CAP-05), and CAP-04's structural
non-blocking guarantee -- a stalled telemetry consumer provably affects
neither the archive queue nor the producer's per-submit call time, and
`submit()` never raises `queue.Full` to the caller.

Task 2 adds CAP-01's "one implementation, two buses in one stream" proof
and CAP-06's frame-context error accounting with per-frame-id log rate
limiting.

Queue depths in these tests are always small, explicit literal values --
never the shipped `config/logger.json`'s -- so a config tune can never
change what an assertion here means.
"""

import logging
import threading
import time
from pathlib import Path

from telemetry.capture.fanout import CapturedFrame, FanOut
from telemetry.synth.generator import SyntheticFrameSource
from telemetry.wire.dictionary import IdDictionary, build_id_dictionary
from telemetry.wire.encoder import MAX_PAYLOAD_BYTES
from telemetry.wire.frame_source import RawFrame

CHANNEL_A = "MAIN"
CHANNEL_B = "SENSOR"


def _make_frame(
    frame_id: int,
    is_extended: bool = False,
    payload: bytes = b"\x01",
    timestamp_us: int = 0,
) -> RawFrame:
    return RawFrame(
        timestamp_us=timestamp_us,
        frame_id=frame_id,
        is_extended=is_extended,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Task 1: divergent overflow policies, discard/filter accounting, HWMs, CAP-04
# ---------------------------------------------------------------------------


def test_discard_counting():
    """CAP-05's own named node: a telemetry deque of depth four, twenty
    allowlisted frames submitted with no consumer draining -- the discard
    count is exactly sixteen, and the deque holds exactly the last four
    frames submitted, in order (drop-oldest: freshest data survives)."""
    stop_event = threading.Event()
    allowlist = frozenset({(0x100, False)})
    fan_out = FanOut(
        archive_maxsize=1000,
        telemetry_maxsize=4,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
    )

    for i in range(20):
        fan_out.submit(
            CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100, timestamp_us=i))
        )

    assert fan_out.counters.telemetry_discard_count == 16
    survivors = [captured.frame.timestamp_us for captured in fan_out.telemetry_queue]
    assert survivors == [16, 17, 18, 19]


def test_discard_counting_fewer_than_depth_is_zero():
    stop_event = threading.Event()
    allowlist = frozenset({(0x100, False)})
    fan_out = FanOut(
        archive_maxsize=1000,
        telemetry_maxsize=4,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
    )

    for i in range(3):
        fan_out.submit(
            CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100, timestamp_us=i))
        )

    assert fan_out.counters.telemetry_discard_count == 0


def test_filtered_frame_never_reaches_deque_and_is_not_counted_as_a_discard():
    """A filtered frame and a dropped frame are different events and must
    not share a counter."""
    stop_event = threading.Event()
    allowlist = frozenset({(0x100, False)})  # 0x200 is deliberately NOT allowlisted
    fan_out = FanOut(
        archive_maxsize=1000,
        telemetry_maxsize=4,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
    )

    fan_out.submit(
        CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x200, timestamp_us=0))
    )

    assert fan_out.counters.telemetry_discard_count == 0
    assert fan_out.counters.telemetry_filtered_count == 1
    assert len(fan_out.telemetry_queue) == 0


def test_archive_accepts_exactly_capacity_frames_in_order_no_discards():
    stop_event = threading.Event()
    fan_out = FanOut(
        archive_maxsize=10,
        telemetry_maxsize=1,
        telemetry_allowlist=frozenset(),
        stop_event=stop_event,
    )

    for i in range(10):
        fan_out.submit(
            CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100 + i, timestamp_us=i))
        )

    assert not stop_event.is_set()
    assert not fan_out.counters.archive_overflow

    recovered = []
    while not fan_out.archive_queue.empty():
        recovered.append(fan_out.archive_queue.get_nowait())
    assert [c.frame.timestamp_us for c in recovered] == list(range(10))


def test_archive_overflow_is_fatal_logs_full_context_stops_and_stays_stopped(caplog):
    """CAP-03: the archive queue never drops. Submitting one frame beyond
    capacity sets the stop event, sets the overflow flag, emits a critical
    log record naming the frame's channel/id/timestamp, and does not
    silently continue accepting further frames as though nothing
    happened."""
    stop_event = threading.Event()
    fan_out = FanOut(
        archive_maxsize=2,
        telemetry_maxsize=1,
        telemetry_allowlist=frozenset(),
        stop_event=stop_event,
    )

    for i in range(2):
        fan_out.submit(
            CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100 + i, timestamp_us=i))
        )
    assert not stop_event.is_set()

    overflow_frame = _make_frame(0x2AB, timestamp_us=424242)
    with caplog.at_level(logging.CRITICAL):
        fan_out.submit(CapturedFrame(channel=CHANNEL_B, frame=overflow_frame))

    assert stop_event.is_set()
    assert fan_out.counters.archive_overflow
    assert fan_out.archive_queue.qsize() == 2  # the overflowing frame never entered

    critical_records = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert critical_records
    joined = " ".join(r.getMessage() for r in critical_records)
    assert CHANNEL_B in joined
    assert "0x2AB" in joined  # frame_id, formatted as 0x%X
    assert "424242" in joined

    # Does not silently continue: the queue never grows past capacity, and
    # a further submit still hits the same fatal condition.
    fan_out.submit(
        CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x2AC, timestamp_us=99))
    )
    assert fan_out.archive_queue.qsize() == 2


def test_stalled_telemetry_consumer_does_not_affect_archive_delivery_or_submit_time():
    """CAP-04: a telemetry consumer that never drains at all does not
    change how many frames reach the archive queue, nor the producer's
    per-submit call time, across a burst several times the telemetry
    depth."""
    stop_event = threading.Event()
    telemetry_depth = 5
    allowlist = frozenset({(0x100, False)})
    fan_out = FanOut(
        archive_maxsize=100_000,
        telemetry_maxsize=telemetry_depth,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
    )

    burst = telemetry_depth * 50
    max_submit_duration = 0.0
    for i in range(burst):
        started = time.perf_counter()
        fan_out.submit(
            CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100, timestamp_us=i))
        )
        max_submit_duration = max(max_submit_duration, time.perf_counter() - started)

    assert not stop_event.is_set()
    assert fan_out.archive_queue.qsize() == burst
    assert len(fan_out.telemetry_queue) == telemetry_depth
    assert max_submit_duration < 0.05, (
        "a submit() call should never pay any cost proportional to the "
        "stalled telemetry consumer"
    )


def test_submit_never_raises_under_sustained_telemetry_overflow():
    """`submit` never raises `queue.Full` out to the caller and never
    blocks: it completes for every frame in a burst that overflows the
    telemetry side many times over."""
    stop_event = threading.Event()
    allowlist = frozenset({(0x100, False)})
    fan_out = FanOut(
        archive_maxsize=100_000,
        telemetry_maxsize=2,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
    )

    for i in range(1000):
        fan_out.submit(
            CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100, timestamp_us=i))
        )  # must never raise

    assert fan_out.counters.telemetry_discard_count == 998
    assert fan_out.counters.frames_submitted == 1000


def test_fanout_module_imports_nothing_from_archive_or_link():
    """CAP-04's structural guarantee, proven statically rather than by
    behavior alone: the telemetry consumer must hold no handle that could
    apply backpressure to capture or the archive path -- which requires
    `telemetry.capture.fanout` to import nothing from `telemetry.archive`
    or `telemetry.link` in the first place. The one-directional dependency
    is what makes the guarantee structural, not a promise a future edit
    could quietly break."""
    import ast
    import inspect
    from pathlib import Path

    from telemetry.capture import fanout as fanout_module

    source_path = inspect.getsourcefile(fanout_module)
    tree = ast.parse(Path(source_path).read_text(encoding="utf-8"))

    imported_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden = [
        m for m in imported_modules if m.startswith(("telemetry.archive", "telemetry.link"))
    ]
    assert forbidden == [], (
        f"fanout.py must not import from telemetry.archive/telemetry.link, "
        f"found: {forbidden}"
    )


def test_high_water_marks_track_deepest_occupancy_and_never_decrease():
    stop_event = threading.Event()
    allowlist = frozenset({(0x100, False)})
    fan_out = FanOut(
        archive_maxsize=10,
        telemetry_maxsize=3,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
    )

    for i in range(3):
        fan_out.submit(
            CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100, timestamp_us=i))
        )
    assert fan_out.counters.archive_high_water_mark == 3
    assert fan_out.counters.telemetry_high_water_mark == 3

    # Draining both queues must not decrease either high-water mark.
    while not fan_out.archive_queue.empty():
        fan_out.archive_queue.get_nowait()
    fan_out.telemetry_queue.clear()

    assert fan_out.counters.archive_high_water_mark == 3
    assert fan_out.counters.telemetry_high_water_mark == 3

    for i in range(2):
        fan_out.submit(
            CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100, timestamp_us=100 + i))
        )
    assert fan_out.counters.archive_high_water_mark == 3  # re-filling to 2 stays under 3
    assert fan_out.counters.telemetry_high_water_mark == 3


# ---------------------------------------------------------------------------
# Task 2: dual-bus capture in one stream (CAP-01), and error context (CAP-06)
# ---------------------------------------------------------------------------


def _empty_dictionary() -> IdDictionary:
    """An `IdDictionary` that knows no ids at all -- used to force the
    unknown-id half of the CAP-06 precheck deterministically, without
    depending on the real DBC containing (or not containing) any
    particular id."""
    return IdDictionary(index={}, reverse={}, dict_version=0, dbc_path=Path("unused"))


def test_dual_bus_capture(dbc, gate_config, logger_config):
    """CAP-01's own named node: one `FanOut` instance carries frames from
    both configured channel names, interleaved, driven through
    `SyntheticFrameSource` so the payloads are real DBC-valid frames rather
    than invented bytes.

    This proves one implementation carries both buses concurrently in one
    stream -- CAP-01's first clause. It does NOT prove the duplicate
    legacy implementation has been removed from the repository (that
    clause is deliberately deferred to Phase 2 by user decision -- see
    01-CONTEXT.md's Deferred section), and it does not substitute for the
    hardware-attached dual-bus check 01-VALIDATION.md lists as
    manual-only.
    """
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)

    channel_names = [c.name for c in logger_config.channels]
    assert len(channel_names) >= 2, "test assumes at least two configured channels"
    channel_a, channel_b = channel_names[0], channel_names[1]

    message_names = [m.name for m in dbc.messages][:2]
    source = SyntheticFrameSource(
        dbc, dictionary, gate_config, "typical", duration_s=0.5, only_message_names=message_names
    )
    frames = list(source.frames())
    assert frames, "expected at least one synthetic frame for the selected subset"

    stop_event = threading.Event()
    fan_out = FanOut(
        archive_maxsize=10_000,
        telemetry_maxsize=10_000,
        telemetry_allowlist=frozenset(),  # CAP-01 is proven on the archive side here
        stop_event=stop_event,
    )

    expected_counts = {channel_a: 0, channel_b: 0}
    for i, frame in enumerate(frames):
        channel = channel_a if i % 2 == 0 else channel_b
        expected_counts[channel] += 1
        fan_out.submit(CapturedFrame(channel=channel, frame=frame))

    assert not stop_event.is_set()

    archived = []
    while not fan_out.archive_queue.empty():
        archived.append(fan_out.archive_queue.get_nowait())

    assert len(archived) == len(frames)
    assert [c.frame for c in archived] == frames  # one stream, submission order preserved

    actual_counts = {channel_a: 0, channel_b: 0}
    for captured in archived:
        actual_counts[captured.channel] += 1
    assert actual_counts == expected_counts


def test_unknown_id_counted_and_logged_archive_still_receives_the_frame(caplog):
    """CAP-06: a frame whose id is absent from the ID dictionary is counted
    as a telemetry-path encode error and logged with its channel, id, and
    timestamp. The archive path still receives it -- the archive is not
    dictionary-bound and must not lose a frame just because the live path
    cannot encode it."""
    stop_event = threading.Event()
    key = (0x321, False)
    fan_out = FanOut(
        archive_maxsize=10,
        telemetry_maxsize=10,
        telemetry_allowlist=frozenset({key}),
        stop_event=stop_event,
        dictionary=_empty_dictionary(),
    )
    frame = _make_frame(0x321, timestamp_us=555)

    with caplog.at_level(logging.WARNING):
        fan_out.submit(CapturedFrame(channel=CHANNEL_A, frame=frame))

    assert fan_out.counters.telemetry_unknown_id_count == 1
    assert len(fan_out.telemetry_queue) == 0  # never reached the telemetry deque

    assert fan_out.archive_queue.qsize() == 1  # archive is unaffected
    archived = fan_out.archive_queue.get_nowait()
    assert archived.frame == frame

    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records
    joined = " ".join(r.getMessage() for r in warning_records)
    assert CHANNEL_A in joined
    assert "0x321" in joined
    assert "555" in joined


def test_over_length_payload_counted_and_logged_no_unhandled_exception(caplog):
    """An over-length payload is counted and logged the same way as an
    unknown id, and does not propagate an unhandled exception out of
    `submit`."""
    stop_event = threading.Event()
    key = (0x322, False)
    fan_out = FanOut(
        archive_maxsize=10,
        telemetry_maxsize=10,
        telemetry_allowlist=frozenset({key}),
        stop_event=stop_event,
    )
    over_length_payload = bytes(range(MAX_PAYLOAD_BYTES + 3))
    frame = _make_frame(0x322, payload=over_length_payload, timestamp_us=777)

    with caplog.at_level(logging.WARNING):
        fan_out.submit(CapturedFrame(channel=CHANNEL_B, frame=frame))  # must not raise

    assert fan_out.counters.telemetry_payload_too_long_count == 1
    assert len(fan_out.telemetry_queue) == 0
    assert fan_out.archive_queue.qsize() == 1  # archive is unaffected


def test_unexpected_telemetry_error_is_caught_counted_logged_not_swallowed(caplog):
    """CAP-06 also requires an unexpected exception from the telemetry
    side to be caught, counted, and logged -- never silently swallowed the
    way `src/new_logger.py`'s bare `except Exception: debug(...)` is."""

    class _ExplodingDictionary:
        def index_of(self, frame_id, is_extended):
            raise RuntimeError("boom -- simulated unexpected failure")

    stop_event = threading.Event()
    key = (0x324, False)
    fan_out = FanOut(
        archive_maxsize=10,
        telemetry_maxsize=10,
        telemetry_allowlist=frozenset({key}),
        stop_event=stop_event,
        dictionary=_ExplodingDictionary(),
    )
    frame = _make_frame(0x324, timestamp_us=888)

    with caplog.at_level(logging.WARNING):
        fan_out.submit(CapturedFrame(channel=CHANNEL_A, frame=frame))  # must not propagate

    assert fan_out.counters.telemetry_unexpected_error_count == 1
    assert len(fan_out.telemetry_queue) == 0
    assert fan_out.archive_queue.qsize() == 1

    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("boom" in r.getMessage() for r in warning_records)


def test_repeated_unknown_id_errors_are_rate_limited_but_still_counted(caplog):
    """The first occurrence per frame id is logged in full; repeats are
    counted without re-logging, so a persistently unknown id cannot flood
    the log at bus rate and hide everything else. Report the suppressed
    totals on the counters object so nothing is actually lost."""
    stop_event = threading.Event()
    key = (0x323, False)
    fan_out = FanOut(
        archive_maxsize=1000,
        telemetry_maxsize=1000,
        telemetry_allowlist=frozenset({key}),
        stop_event=stop_event,
        dictionary=_empty_dictionary(),
    )

    with caplog.at_level(logging.WARNING):
        for i in range(50):
            fan_out.submit(
                CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x323, timestamp_us=i))
            )

    assert fan_out.counters.telemetry_unknown_id_count == 50
    assert fan_out.counters.telemetry_error_log_suppressed_count == 49

    matching_records = [
        r for r in caplog.records if r.levelno >= logging.WARNING and "0x323" in r.getMessage()
    ]
    assert len(matching_records) == 1  # first occurrence logged in full, repeats suppressed
