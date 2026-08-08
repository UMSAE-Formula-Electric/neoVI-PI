"""
Requirements covered: GND-03.
Filled by: 02-03.

In-process, fast, no subprocess and no sockets -- drives
`telemetry.ground.simulate.feed_frames` and `build_car_link` directly, following
`tests/test_fanout.py`'s in-process construction style: real objects, no mocks of project code,
and every bound a small literal in this file rather than a value read from `config/logger.json`,
so a config tune can never change what an assertion here means.

The recording stand-in link (`_RecordingLink`) implements only the three methods the `Link`
protocol declares and appends each sent payload to a list -- a test double for an external
transport, not for project logic, which is the distinction that keeps this test honest.

Not written: no test asserting the dashboard renders the simulated values. That needs a browser,
which is not available to the automated suite; it is the two-terminal human check named in
02-03-PLAN.md's Task 2 `<verify>`, stated as such rather than faked with a file-content assertion.
"""

import threading
import time
from collections import deque
from dataclasses import replace

import pytest

from telemetry.ground.deframe import Deframer
from telemetry.ground.simulate import (
    UnreachableLinkKind,
    build_car_link,
    feed_frames,
)
from telemetry.logger.pipeline import TelemetryPipeline
from telemetry.synth.generator import SyntheticFrameSource
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import Encoder

CHANNEL = "MAIN"
BATCH_FRAMES = 100
BATCH_MAX_AGE_S = 10.0
TELEMETRY_QUEUE_DEPTH = 1000
# A high pacing multiplier so these tests run in well under a second of real
# wall-clock time even though the simulated stream spans a full second.
FAST_PACING = 1000.0


class _RecordingLink:
    """A `Link` protocol test double for an external transport (not project logic): implements
    only the three methods `telemetry.link.base.Link` declares and appends every sent payload to
    a list so a test can inspect exactly what left the wire."""

    def __init__(self) -> None:
        self.sent: list = []
        self.closed = False

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, timeout=None):
        return None

    def close(self) -> None:
        self.closed = True


def _synthetic_source(dbc, dictionary, gate_config, logger_config, duration_s=1.0):
    return SyntheticFrameSource(
        db=dbc,
        dictionary=dictionary,
        config=gate_config,
        bracket_name="typical",
        duration_s=duration_s,
        only_message_names=logger_config.telemetry.allowlist,
    )


def _pipeline(dictionary, telemetry_queue, link, stop_event):
    return TelemetryPipeline(
        telemetry_queue=telemetry_queue,
        encoder=Encoder(dictionary),
        link=link,
        dict_version=dictionary.dict_version,
        batch_frames=BATCH_FRAMES,
        batch_max_age_s=BATCH_MAX_AGE_S,
        stop_event=stop_event,
        poll_timeout_s=0.01,
    )


def test_simulator_output_deframes_to_allowlisted_dbc_messages(dbc, logger_config, gate_config):
    """Every batch the simulator sends survives COBS+CRC deframing with zero framing failures,
    and every recovered frame's id resolves to a DBC message whose name is in the config's
    telemetry allowlist. Catches: a simulator that emits bytes the real ground station cannot
    read, and one that leaks non-allowlisted traffic onto the live path -- this is the assertion
    that makes the simulator trustworthy as a manual-test instrument."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    link = _RecordingLink()
    stop_event = threading.Event()
    telemetry_queue = deque(maxlen=TELEMETRY_QUEUE_DEPTH)

    frame_source = _synthetic_source(dbc, dictionary, gate_config, logger_config, duration_s=1.0)

    pipeline = _pipeline(dictionary, telemetry_queue, link, stop_event)
    pipeline.start()
    try:
        frames_fed = feed_frames(
            frame_source=frame_source,
            telemetry_queue=telemetry_queue,
            channel_name=CHANNEL,
            stop_event=stop_event,
            pacing=FAST_PACING,
        )
        # Give the pipeline thread time to drain every frame it was just fed
        # before signalling it to stop -- TelemetryPipeline checks
        # stop_event BEFORE popping the deque (it is lossy by design for
        # whatever is still queued at stop), so setting stop_event too
        # early would race the thread into exiting having encoded nothing
        # at all rather than proving anything about the bytes it produces.
        deadline = time.monotonic() + 2.0
        while pipeline.counters.frames_sent < frames_fed and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pipeline.counters.frames_sent == frames_fed, (
            "pipeline did not drain every fed frame within the deadline"
        )
    finally:
        stop_event.set()
        pipeline.join(timeout=2.0)

    assert frames_fed > 0
    assert link.sent, "the simulator must have sent at least one framed batch"

    deframer = Deframer(dictionary)
    allowlist_names = set(logger_config.telemetry.allowlist)
    decoded_message_names = set()
    for framed in link.sent:
        for recovered_batch in deframer.feed(framed):
            for raw_frame in recovered_batch:
                message = dbc.get_message_by_frame_id(
                    raw_frame.frame_id, force_extended_id=raw_frame.is_extended
                )
                decoded_message_names.add(message.name)

    # Zero framing failures of any kind -- proves the bytes are genuinely
    # well-formed, not merely non-empty.
    assert deframer.counters.cobs_failures == 0
    assert deframer.counters.crc_failures == 0
    assert deframer.counters.batch_format_failures == 0
    assert deframer.counters.record_decode_failures == 0
    assert deframer.counters.batches_ok > 0

    assert decoded_message_names, "at least one message must have decoded"
    assert decoded_message_names <= allowlist_names, (
        f"decoded non-allowlisted message(s): {decoded_message_names - allowlist_names}"
    )


def test_simulator_refuses_a_link_kind_that_cannot_reach_another_process(logger_config):
    """Constructing the car link with the in-process loopback kind raises with a message naming
    the problem. Catches the silent-no-op demo: a simulator that appears to run while nothing can
    ever receive it."""
    loopback_link_config = replace(logger_config.link, kind="loopback")

    with pytest.raises(UnreachableLinkKind, match="loopback"):
        build_car_link(loopback_link_config)


def test_pacing_multiplier_bounds_a_short_run(dbc, logger_config, gate_config):
    """A short run at a high pacing multiplier completes well inside a generous literal
    wall-clock bound. Catches a pacing bug that sleeps on absolute rather than relative
    timestamps, which would make the simulator appear hung."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    stop_event = threading.Event()
    telemetry_queue = deque(maxlen=TELEMETRY_QUEUE_DEPTH)

    # Two full simulated seconds, played back at 1000x -- naively sleeping on
    # absolute rather than relative (offset-from-first-frame) timestamps
    # would make this hang for roughly the full 2 real seconds instead of
    # completing in a couple of milliseconds.
    frame_source = _synthetic_source(dbc, dictionary, gate_config, logger_config, duration_s=2.0)

    start = time.monotonic()
    frames_fed = feed_frames(
        frame_source=frame_source,
        telemetry_queue=telemetry_queue,
        channel_name=CHANNEL,
        stop_event=stop_event,
        pacing=FAST_PACING,
    )
    elapsed = time.monotonic() - start

    assert frames_fed > 0
    assert elapsed < 2.0, f"a 1000x-paced 2s run took {elapsed:.3f}s wall-clock -- looks hung"
