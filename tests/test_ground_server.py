"""
Requirements covered: GND-02, GND-04, GND-05.

Task 1 proves one decoded signal travelling link -> decode -> state store ->
SSE -> a connected client, end to end, against real production code: a real
`DashboardServer` bound to `127.0.0.1:0`, a real `LoopbackLink` fed real
COBS-framed bytes built through the same `Encoder`/`pack_batch`/`cobs_frame`
chain `tests/test_end_to_end.py` uses, and `urllib` as the bounded SSE
client stand-in -- no mocks, no browser, no new dependency (02-01-PLAN.md
Task 1's own stated harness).

Two of the seven behaviors (`build_message_index`'s channel derivation and
its collision guard) need no server or link at all -- they are pure
`telemetry.ground.state` unit tests and are written that way, rather than
routing them through the full stack for no reason.

Task 2 adds the bounded per-client fan-out (drop-oldest, never-blocks) and
hardened-route behaviors, driven directly against `SseHub`/`DashboardServer`
with no link involved -- none of Task 2's failure modes live on the
link/decode side of the system.

SSE wire framing here is deliberately two lines per event/heartbeat (a
`data:`/`:`-prefixed line followed by one blank line) -- no `event:` line,
per 02-01-PLAN.md's interface contract -- so the read helpers below are NOT
the three-line shape some SSE probes assume.

Queue depths and timeouts in these tests are always small, explicit literal
values -- never read from `config/logger.json` -- so a config tune can
never change what an assertion here means (mirrors `tests/test_fanout.py`'s
stated rationale).
"""

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from telemetry.framing.cobs_frame import frame as cobs_frame
from telemetry.ground.cli import GroundConsumerCounters, run_consumer_loop
from telemetry.ground.deframe import Deframer
from telemetry.ground.server import (
    SSE_CLIENT_QUEUE_MAXSIZE,
    DashboardServer,
    SseHub,
)
from telemetry.ground.state import (
    GroundStateError,
    SignalState,
    build_message_index,
)
from telemetry.link.loopback import LoopbackLink
from telemetry.wire.batcher import pack_batch
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import Encoder
from telemetry.wire.frame_source import RawFrame

# Messages known (by direct DBC/gate-config measurement, not transcribed
# prose) to belong to bus1/MAIN and bus2/SENSOR respectively, both on
# config/logger.json's telemetry allowlist.
BUS1_MESSAGE = "M195_Pedal_Press_Percent"
BUS1_SIGNAL = "Pedal_Press_Percent"
BUS1_CHANNEL = "MAIN"

BUS2_MESSAGE = "Battery_Volt_1_Overall_Param_Std"
BUS2_CHANNEL = "SENSOR"

SSE_READ_TIMEOUT_S = 5.0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _frame_for_message(db, message_name: str, timestamp_us: int, **signal_overrides) -> RawFrame:
    """Like `tests/test_end_to_end.py::_frame_for_message`: an all-zero
    payload (`strict=False` so a nonzero-minimum signal still encodes),
    overridden with any explicit `signal_overrides`."""
    message = db.get_message_by_name(message_name)
    values = {s.name: 0 for s in message.signals}
    values.update(signal_overrides)
    payload = message.encode(values, strict=False)
    return RawFrame(
        timestamp_us=timestamp_us,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=payload,
    )


def _framed_batch(dictionary, frames: List[RawFrame], base_timestamp_us: int) -> bytes:
    """Encode `frames` into one CFR batch, exactly as `main()`'s wiring
    would on the car side: `Encoder.encode` -> `pack_batch` -> `cobs_frame`.
    A fresh `Encoder` per call keeps each test's per-ID keyframe/delta state
    independent of every other test's."""
    encoder = Encoder(dictionary)
    records = [encoder.encode(f, batch_base_timestamp_us=base_timestamp_us) for f in frames]
    batch_payload = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=base_timestamp_us,
        batch_seq=0,
        records=records,
    )
    return cobs_frame(batch_payload)


def _decode_sse_bytes(frame_bytes: bytes) -> dict:
    """Inverse of `telemetry.ground.server._sse_frame`: a `data: {...}\\n\\n`
    frame back to its JSON payload."""
    text = frame_bytes.decode("utf-8")
    assert text.startswith("data: ") and text.endswith("\n\n"), (
        f"not a data frame in the two-line generic-message shape: {text!r}"
    )
    return json.loads(text[len("data: ") : -2])


def _read_one_sse_event(response, timeout_s: float = SSE_READ_TIMEOUT_S) -> dict:
    """Read exactly one non-heartbeat SSE event from a real `urlopen`
    response: a `data:` line followed by its terminating blank line.
    Heartbeat comment lines (`: heartbeat` + blank line) are transparently
    skipped -- SSE_HEARTBEAT_S is 1.0s, so a slow-arriving event can
    legitimately be preceded by one or more of them. Bounded by wall-clock
    `timeout_s`, not merely each individual socket read's own timeout."""
    deadline = time.monotonic() + timeout_s
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"no SSE event received within {timeout_s}s")
        line = response.readline()
        if not line:
            continue
        text = line.decode("utf-8").rstrip("\n")
        if text.startswith(":"):
            response.readline()  # the heartbeat comment's blank-line terminator
            continue
        if text.startswith("data:"):
            response.readline()  # this event's blank-line terminator
            return json.loads(text[len("data:") :].strip())


@dataclass
class _DashboardHarness:
    """Wires `SignalState` + `SseHub` + `DashboardServer` + a real
    `LoopbackLink`/`Deframer`/`run_consumer_loop` exactly as `cli.py`'s
    `main()` does in `--serve` mode, but driven directly with no CLI or
    subprocess involved -- matching Task 1's own stated test harness."""

    dbc: object
    dictionary: object
    signal_state: SignalState
    hub: SseHub
    server: DashboardServer
    link: LoopbackLink
    deframer: Deframer
    stop_event: threading.Event
    server_thread: threading.Thread
    consumer_thread: threading.Thread
    counters: GroundConsumerCounters = field(default_factory=GroundConsumerCounters)

    def events_url(self) -> str:
        return f"http://127.0.0.1:{self.server.port}/events"

    def send_frames(self, frames: List[RawFrame], base_timestamp_us: int) -> None:
        framed = _framed_batch(self.dictionary, frames, base_timestamp_us)
        self.link.send(framed)

    def wait_until_applied(self, count: int, timeout_s: float = SSE_READ_TIMEOUT_S) -> None:
        deadline = time.monotonic() + timeout_s
        while self.signal_state.counters.records_applied < count:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"signal_state only applied "
                    f"{self.signal_state.counters.records_applied}/{count} record(s) "
                    f"within {timeout_s}s"
                )
            time.sleep(0.01)

    def close(self) -> None:
        self.stop_event.set()
        self.consumer_thread.join(timeout=SSE_READ_TIMEOUT_S)
        self.server.shutdown()
        self.server_thread.join(timeout=SSE_READ_TIMEOUT_S)
        self.server.server_close()
        self.link.close()


def _build_harness(dbc, logger_config, gate_config) -> _DashboardHarness:
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    message_index = build_message_index(dbc, logger_config, gate_config)
    signal_state = SignalState(message_index)
    hub = SseHub()
    server = DashboardServer(
        host="127.0.0.1", port=0, hub=hub, snapshot_provider=signal_state.snapshot
    )

    def on_record(**fields) -> None:
        payload = signal_state.update(
            message_name=fields["message_name"],
            signal=fields["signal"],
            value=fields["value"],
            unit=fields["unit"],
            now_ms=int(time.time() * 1000),
        )
        hub.broadcast(payload)

    link = LoopbackLink()
    deframer = Deframer(dictionary)
    stop_event = threading.Event()
    counters = GroundConsumerCounters()

    server_thread = threading.Thread(
        target=server.serve_forever, name="test-dashboard-server", daemon=True
    )
    server_thread.start()

    consumer_thread = threading.Thread(
        target=run_consumer_loop,
        kwargs=dict(
            link=link,
            deframer=deframer,
            db=dbc,
            stop_event=stop_event,
            on_record=on_record,
            counters=counters,
            recv_timeout_s=0.05,
            health_interval_s=100.0,
        ),
        name="test-ground-consumer",
        daemon=True,
    )
    consumer_thread.start()

    return _DashboardHarness(
        dbc=dbc,
        dictionary=dictionary,
        signal_state=signal_state,
        hub=hub,
        server=server,
        link=link,
        deframer=deframer,
        stop_event=stop_event,
        server_thread=server_thread,
        consumer_thread=consumer_thread,
        counters=counters,
    )


# ---------------------------------------------------------------------------
# Pure `telemetry.ground.state` unit tests -- no server, no link.
# ---------------------------------------------------------------------------


def test_state_channel_comes_from_the_dbc_bus_assignment(dbc, logger_config, gate_config):
    """An allowlisted message known (by direct measurement) to belong to
    bus1 lands under channel MAIN, and one on bus2 lands under SENSOR --
    catches a `KeyError` on a non-existent `channel` field or a state dict
    keyed by `None` (02-RESEARCH.md Pitfall 2)."""
    index = build_message_index(dbc, logger_config, gate_config)
    state = SignalState(index)

    bus1_payload = state.update(
        message_name=BUS1_MESSAGE, signal=BUS1_SIGNAL, value=42, unit="%", now_ms=1_000
    )
    bus2_message = dbc.get_message_by_name(BUS2_MESSAGE)
    bus2_signal_name = bus2_message.signals[0].name
    bus2_payload = state.update(
        message_name=BUS2_MESSAGE, signal=bus2_signal_name, value=0, unit=None, now_ms=1_000
    )

    assert bus1_payload["channel"] == BUS1_CHANNEL
    assert bus2_payload["channel"] == BUS2_CHANNEL

    snapshot = state.snapshot()
    bus1_id_key = f"0x{dbc.get_message_by_name(BUS1_MESSAGE).frame_id:X}"
    bus2_id_key = f"0x{bus2_message.frame_id:X}"
    assert BUS1_CHANNEL in snapshot
    assert bus1_id_key in snapshot[BUS1_CHANNEL]
    assert snapshot[BUS1_CHANNEL][bus1_id_key]["signals"][BUS1_SIGNAL]["value"] == 42
    assert BUS2_CHANNEL in snapshot
    assert bus2_id_key in snapshot[BUS2_CHANNEL]


def test_duplicate_message_id_key_raises(logger_config, gate_config):
    """Two distinct messages that would collide on the same
    `(channel, id_key)` pair raise `GroundStateError` naming both -- catches
    two different messages silently overwriting each other in the state
    dict. Built from a minimal fake `db` exposing only the attributes
    `build_message_index`/`assign_rates` actually read (`name`, `frame_id`,
    `is_extended_frame`, `cycle_time`, `senders`), both with no declared
    sender so both resolve to `gate.json`'s `bus_assignment.default_bus`
    (bus1 -> MAIN) and the same collision-triggering `frame_id`."""

    @dataclass
    class _FakeMessage:
        name: str
        frame_id: int
        is_extended_frame: bool = False
        cycle_time: Optional[int] = None
        senders: List[str] = field(default_factory=list)

    class _FakeDb:
        def __init__(self, messages):
            self.messages = messages

    fake_db = _FakeDb(
        [
            _FakeMessage(name="FakeMessageA", frame_id=0x999),
            _FakeMessage(name="FakeMessageB", frame_id=0x999),
        ]
    )

    with pytest.raises(GroundStateError) as exc_info:
        build_message_index(fake_db, logger_config, gate_config)

    assert "FakeMessageA" in str(exc_info.value)
    assert "FakeMessageB" in str(exc_info.value)


def test_real_dbc_message_index_has_no_collisions(dbc, logger_config, gate_config):
    """`build_message_index` over the checked-in DBC and `config/logger.json`
    succeeds and produces one entry per DBC message -- catches shipping a
    fail-closed guard that the project's own DBC trips on startup."""
    index = build_message_index(dbc, logger_config, gate_config)
    assert len(index) == len(dbc.messages)


# ---------------------------------------------------------------------------
# Full-stack SSE tests -- real DashboardServer + real LoopbackLink fed real
# COBS-framed bytes.
# ---------------------------------------------------------------------------


def test_first_event_is_snapshot(dbc, logger_config, gate_config):
    """With state already populated by one decoded record, a newly opened
    `/events` stream's FIRST event is `type == "snapshot"` whose `state`
    contains that signal's current value -- catches a server that only
    pushes deltas, leaving a mid-session browser blank until each signal
    next updates (GND-05)."""
    harness = _build_harness(dbc, logger_config, gate_config)
    try:
        subject = _frame_for_message(dbc, BUS1_MESSAGE, timestamp_us=1_000, **{BUS1_SIGNAL: 42})
        harness.send_frames([subject], base_timestamp_us=1_000)
        harness.wait_until_applied(1)

        response = urllib.request.urlopen(harness.events_url(), timeout=SSE_READ_TIMEOUT_S)
        try:
            first_event = _read_one_sse_event(response)
        finally:
            response.close()

        assert first_event["type"] == "snapshot"
        id_key = f"0x{dbc.get_message_by_name(BUS1_MESSAGE).frame_id:X}"
        signals = first_event["state"][BUS1_CHANNEL][id_key]["signals"]
        assert signals[BUS1_SIGNAL]["value"] == 42
    finally:
        harness.close()


def test_client_receives_update_after_snapshot(dbc, logger_config, gate_config):
    """With a client already connected, feeding one framed batch into the
    link produces an event with `type == "update"` carrying `channel`,
    `id`, `name`, `signal`, `value`, `unit`, `ts` -- catches state that
    updates but never fans out (GND-04)."""
    harness = _build_harness(dbc, logger_config, gate_config)
    try:
        response = urllib.request.urlopen(harness.events_url(), timeout=SSE_READ_TIMEOUT_S)
        try:
            snapshot_event = _read_one_sse_event(response)
            assert snapshot_event["type"] == "snapshot"
            assert snapshot_event["state"] == {}

            subject = _frame_for_message(
                dbc, BUS1_MESSAGE, timestamp_us=2_000, **{BUS1_SIGNAL: 7}
            )
            harness.send_frames([subject], base_timestamp_us=2_000)

            update_event = _read_one_sse_event(response)
        finally:
            response.close()

        message = dbc.get_message_by_name(BUS1_MESSAGE)
        signal_def = message.get_signal_by_name(BUS1_SIGNAL)

        assert update_event["type"] == "update"
        assert update_event["channel"] == BUS1_CHANNEL
        assert update_event["id"] == f"0x{message.frame_id:X}"
        assert update_event["name"] == BUS1_MESSAGE
        assert update_event["signal"] == BUS1_SIGNAL
        assert update_event["value"] == 7
        assert update_event["unit"] == (signal_def.unit or "")
        assert "ts" in update_event
    finally:
        harness.close()


def test_update_ts_is_wall_clock_not_frame_timestamp(dbc, logger_config, gate_config):
    """The `ts` on an update event is within a few seconds of
    `time.time() * 1000` at assert time, and is NOT equal to the frame's
    deliberately absurd `timestamp_us`. Catches 02-RESEARCH.md Pitfall 1 --
    the bug that would silently make 02-02's staleness dimming
    meaningless."""
    harness = _build_harness(dbc, logger_config, gate_config)
    try:
        response = urllib.request.urlopen(harness.events_url(), timeout=SSE_READ_TIMEOUT_S)
        try:
            _read_one_sse_event(response)  # snapshot, discarded

            absurd_timestamp_us = 1
            subject = _frame_for_message(dbc, BUS1_MESSAGE, timestamp_us=absurd_timestamp_us)
            harness.send_frames([subject], base_timestamp_us=absurd_timestamp_us)

            update_event = _read_one_sse_event(response)
        finally:
            response.close()

        now_ms = int(time.time() * 1000)
        assert update_event["ts"] != absurd_timestamp_us
        assert abs(update_event["ts"] - now_ms) < 5_000
    finally:
        harness.close()


def test_shutdown_from_decode_thread_returns_promptly():
    """With `serve_forever()` running on a non-main thread (the test's own
    inversion of production's layout), calling `shutdown()` from another
    thread returns within 2s -- catches a regression toward the deadlocking
    arrangement 02-RESEARCH.md Pitfall 3 describes."""
    hub = SseHub()
    server = DashboardServer(
        host="127.0.0.1", port=0, hub=hub, snapshot_provider=lambda: {}
    )
    server_thread = threading.Thread(
        target=server.serve_forever, name="test-serve-forever", daemon=True
    )
    server_thread.start()
    # Give serve_forever a moment to actually enter its blocking loop before
    # shutdown() is called from this (main) thread.
    time.sleep(0.1)

    start = time.monotonic()
    server.shutdown()
    elapsed = time.monotonic() - start

    server_thread.join(timeout=2.0)
    server.server_close()

    assert elapsed < 2.0, f"shutdown() took {elapsed:.2f}s -- expected a prompt return"
    assert not server_thread.is_alive()


# ---------------------------------------------------------------------------
# Task 2: bounded per-client fan-out and hardened routes -- SseHub /
# DashboardServer only, no link involved.
# ---------------------------------------------------------------------------


def test_slow_client_loses_oldest_not_newest():
    """Registering a client and broadcasting more payloads than its queue's
    maxsize without ever draining it keeps the LAST payload broadcast and
    drops the FIRST, with `frames_dropped_oldest` non-zero -- the
    discriminating assertion a plain `put_nowait`-and-swallow could not
    pass, since that keeps the OLDEST and throws away the NEWEST."""
    hub = SseHub()
    client_queue = hub.register()

    total = SSE_CLIENT_QUEUE_MAXSIZE + 10
    for i in range(total):
        hub.broadcast({"type": "update", "seq": i})

    drained = []
    while True:
        try:
            drained.append(_decode_sse_bytes(client_queue.get_nowait()))
        except queue.Empty:
            break

    assert drained, "expected the client queue to still hold the newest frames"
    assert drained[-1]["seq"] == total - 1
    assert drained[0]["seq"] != 0
    assert hub.counters.frames_dropped_oldest > 0


def test_broadcast_never_blocks_on_a_full_client():
    """With one client queue deliberately left full, a broadcast returns in
    well under a second -- catches a blocking `put()` re-introducing
    downstream the backpressure CAP-04 exists to structurally prevent."""
    hub = SseHub()
    client_queue = hub.register()
    for _ in range(SSE_CLIENT_QUEUE_MAXSIZE):
        client_queue.put_nowait(b"filler")

    start = time.monotonic()
    hub.broadcast({"type": "update", "seq": "final"})
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, f"broadcast() took {elapsed:.2f}s against a full client queue"


def test_unknown_path_returns_404():
    """A request to an unlisted path returns 404 -- catches a naive
    static-file handler resolving attacker-controlled paths (T-02-01)."""
    hub = SseHub()
    server = DashboardServer(host="127.0.0.1", port=0, hub=hub, snapshot_provider=lambda: {})
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        url = f"http://127.0.0.1:{server.port}/../../../../etc/passwd"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url, timeout=SSE_READ_TIMEOUT_S)
        assert exc_info.value.code == 404
    finally:
        server.shutdown()
        server_thread.join(timeout=SSE_READ_TIMEOUT_S)
        server.server_close()


def test_events_response_sends_no_content_length():
    """The `/events` response headers contain no content-length header --
    catches a copy-paste from a static route that would make a client stop
    reading mid-stream (02-RESEARCH.md Pitfall 5)."""
    hub = SseHub()
    server = DashboardServer(host="127.0.0.1", port=0, hub=hub, snapshot_provider=lambda: {})
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        response = urllib.request.urlopen(
            f"http://127.0.0.1:{server.port}/events", timeout=SSE_READ_TIMEOUT_S
        )
        try:
            assert response.headers.get("Content-Length") is None
        finally:
            response.close()
    finally:
        server.shutdown()
        server_thread.join(timeout=SSE_READ_TIMEOUT_S)
        server.server_close()


def test_dead_client_is_unregistered():
    """Closing a client's connection, then broadcasting twice, returns
    `hub.client_count()` to zero within a bounded wait -- catches handler
    threads and queues accumulating for every browser tab ever opened."""
    hub = SseHub()
    server = DashboardServer(host="127.0.0.1", port=0, hub=hub, snapshot_provider=lambda: {})
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        response = urllib.request.urlopen(
            f"http://127.0.0.1:{server.port}/events", timeout=SSE_READ_TIMEOUT_S
        )
        _read_one_sse_event(response)  # snapshot -- confirms registration happened

        deadline = time.monotonic() + SSE_READ_TIMEOUT_S
        while hub.client_count() == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert hub.client_count() == 1

        response.close()
        hub.broadcast({"type": "update", "seq": 1})
        hub.broadcast({"type": "update", "seq": 2})

        deadline = time.monotonic() + SSE_READ_TIMEOUT_S
        while hub.client_count() != 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert hub.client_count() == 0
    finally:
        server.shutdown()
        server_thread.join(timeout=SSE_READ_TIMEOUT_S)
        server.server_close()
