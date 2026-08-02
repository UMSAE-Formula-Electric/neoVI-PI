"""
Requirements covered: ARCH-01, ARCH-05, CAP-03, CAP-04, LINK-01, LINK-02,
LINK-03, LINK-04, GND-01, OPS-04, OPS-05.

The 01-04 tracer: one CAN frame travels the complete Phase 1 path, end to
end, with production code at every layer — capture fan-out -> MCAP archive
on disk, and in parallel capture fan-out -> allowlist filter -> CFR encode
-> batch -> CRC-16 -> COBS -> Link -> deframe -> CFR decode -> DBC decode.
No radio, no vehicle hardware, and no network socket anywhere in this
chain — `LoopbackLink` is the only transport involved.

01-11 widens this file two ways: in-process tests of
`telemetry.ground.cli.run_consumer_loop` (the headless ground station's own
receive-decode-emit loop, driven directly against a `LoopbackLink`), and the
phase's own success-criterion-4 proof at the *process* level — two real
subprocesses (the car-side logger and the headless ground station) connected
over one real loopback UDP socket, with no radio, no vehicle hardware, and
no second machine involved.

`01-05` through `01-13` build outward from this slice; this file is the
proof that the whole spine holds together on one frame before any of that
widening starts.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import cantools

from telemetry.archive.session import mark_done, new_session
from telemetry.archive.writer import ArchiveWriter
from telemetry.capture.fanout import CapturedFrame, FanOut
from telemetry.framing.cobs_frame import frame as cobs_frame
from telemetry.ground.cli import GroundConsumerCounters, run_consumer_loop
from telemetry.ground.deframe import Deframer
from telemetry.link.loopback import LoopbackLink
from telemetry.logger.config import resolve_allowlist
from telemetry.measure.config import GateConfig, load_gate_config
from telemetry.synth.rates import assign_rates
from telemetry.wire.batcher import pack_batch
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import Encoder
from telemetry.wire.frame_source import RawFrame

# The message this tracer carries end to end: single-signal, on the
# critical-channel allowlist in config/logger.json, so both the fan-out's
# allowlist filter and the DBC-decode assertion below have real content to
# exercise.
SUBJECT_MESSAGE = "M195_Pedal_Press_Percent"
SUBJECT_CHANNEL = "MAIN"
SUBJECT_SIGNAL_VALUES = {"Pedal_Press_Percent": 42}

# A second, distinct allowlisted message -- used by the ground-consumer
# tests below wherever a batch needs two different message ids in it (e.g.
# proving one undecodable record does not stop decoding of a good one in
# the same batch).
OTHER_MESSAGE = "M192_Command_Message"

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


def _build_subject_frame(db, timestamp_us: int) -> RawFrame:
    """Build the one `RawFrame` this test carries end to end, its payload
    produced by encoding known signal values through the real DBC — so the
    ground-side assertion can compare against real values, not opaque
    bytes."""
    message = db.get_message_by_name(SUBJECT_MESSAGE)
    payload = message.encode(SUBJECT_SIGNAL_VALUES)
    return RawFrame(
        timestamp_us=timestamp_us,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=payload,
    )


def _frame_for_message(db, message_name: str, timestamp_us: int) -> RawFrame:
    """Like `_build_subject_frame`, but for any named message, all-zero
    signal values (`strict=False` so a signal with a nonzero minimum still
    encodes) -- used where the specific values don't matter, only that the
    message is real and decodable."""
    message = db.get_message_by_name(message_name)
    payload = message.encode({s.name: 0 for s in message.signals}, strict=False)
    return RawFrame(
        timestamp_us=timestamp_us,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=payload,
    )


def test_one_frame_reaches_the_archive_and_the_pit(dbc, logger_config, tmp_path):
    """One frame submitted to the fan-out lands in a readable MCAP archive
    on disk with a `.done` marker beside it, and the same frame arrives on
    the ground side decoded against the DBC to its original signal values,
    having crossed CFR encoding, batching, CRC-16, COBS, and a link — with
    no radio, no vehicle hardware, and no socket in the chain."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    allowlist = resolve_allowlist(logger_config, dbc)

    subject_frame = _build_subject_frame(dbc, timestamp_us=1_000)
    assert (subject_frame.frame_id, subject_frame.is_extended) in allowlist, (
        f"fixture assumption broken: {SUBJECT_MESSAGE} is expected to be on "
        f"config/logger.json's telemetry allowlist"
    )

    stop_event = threading.Event()
    fan_out = FanOut(
        archive_maxsize=logger_config.archive.queue_depth,
        telemetry_maxsize=logger_config.telemetry.queue_depth,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
    )

    session = new_session(tmp_path)
    writer = ArchiveWriter(
        session.mcap_path,
        channel_names=[c.name for c in logger_config.channels],
        flush_every_records=logger_config.archive.flush_every_records,
        flush_every_s=logger_config.archive.flush_every_s,
    )
    encoder = Encoder(dictionary)
    link = LoopbackLink()
    deframer = Deframer(dictionary)

    # --- capture fan-out: one call, two divergent consumers ---
    captured = CapturedFrame(channel=SUBJECT_CHANNEL, frame=subject_frame)
    fan_out.submit(captured)
    assert not stop_event.is_set(), "fan_out.submit must not stop the session on a normal frame"

    # --- archive path: drain the archive queue into the writer, close, mark done ---
    while not fan_out.archive_queue.empty():
        archived = fan_out.archive_queue.get_nowait()
        writer.add(archived.channel, archived.frame)
    writer.close()
    assert writer.is_closed
    mark_done(session, writer)

    assert session.mcap_path.exists()
    assert session.mcap_path.stat().st_size > 0
    assert session.done_path.exists()

    # --- telemetry path: drain the deque, encode, batch, frame, link, deframe, decode ---
    telemetry_records = []
    base_timestamp_us = None
    while fan_out.telemetry_queue:
        telemetry_captured = fan_out.telemetry_queue.popleft()
        if base_timestamp_us is None:
            base_timestamp_us = telemetry_captured.frame.timestamp_us
        cfr = encoder.encode(telemetry_captured.frame, base_timestamp_us)
        telemetry_records.append(cfr)

    assert telemetry_records, "the subject frame must have reached the telemetry deque"

    batch_payload = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=base_timestamp_us,
        batch_seq=0,
        records=telemetry_records,
    )
    framed = cobs_frame(batch_payload)

    link.send(framed)
    received = link.recv(timeout=1.0)
    assert received is not None, "LoopbackLink must deliver what was sent"

    recovered_batches = list(deframer.feed(received))
    assert len(recovered_batches) == 1
    recovered_frames = recovered_batches[0]
    assert len(recovered_frames) == 1
    recovered = recovered_frames[0]

    # Byte-identical recovery of frame_id, extended flag, and payload.
    assert recovered.frame_id == subject_frame.frame_id
    assert recovered.is_extended == subject_frame.is_extended
    assert recovered.payload == subject_frame.payload

    # DBC-decode the recovered payload and confirm the known signal values.
    decoded_signals = dbc.decode_message(recovered.frame_id, recovered.payload)
    assert decoded_signals == SUBJECT_SIGNAL_VALUES

    # LINK-02's discard-and-count is proven, not merely asserted absent by
    # construction: on the clean path, every corruption counter is zero.
    assert deframer.counters.cobs_failures == 0
    assert deframer.counters.crc_failures == 0
    assert deframer.counters.batch_format_failures == 0
    assert deframer.counters.record_decode_failures == 0
    assert deframer.counters.buffer_overflow_count == 0
    assert deframer.counters.batches_ok == 1
    assert deframer.counters.records_decoded == 1


def test_corrupted_batch_is_discarded_and_counted_not_decoded(dbc, logger_config):
    """A batch whose bytes are corrupted in transit is discarded and
    counted rather than decoded — T-01-01's mitigation, proven by flipping
    one byte inside a framed batch and observing the deframer yield
    nothing, raise nothing, and increment exactly one corruption counter."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    subject_frame = _build_subject_frame(dbc, timestamp_us=2_000)

    encoder = Encoder(dictionary)
    cfr = encoder.encode(subject_frame, batch_base_timestamp_us=subject_frame.timestamp_us)
    batch_payload = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=subject_frame.timestamp_us,
        batch_seq=0,
        records=[cfr],
    )
    framed = bytearray(cobs_frame(batch_payload))

    # Flip one byte inside the framed batch (not the trailing 0x00
    # delimiter, so the corrupted frame is still one segment when fed to
    # the deframer).
    corrupt_index = len(framed) // 2
    framed[corrupt_index] ^= 0xFF

    deframer = Deframer(dictionary)
    recovered_batches = list(deframer.feed(bytes(framed)))

    assert recovered_batches == []

    total_corruption_counters = (
        deframer.counters.cobs_failures
        + deframer.counters.crc_failures
        + deframer.counters.batch_format_failures
    )
    assert total_corruption_counters == 1, (
        f"expected exactly one corruption counter incremented, got "
        f"counters={deframer.counters!r}"
    )
    assert deframer.counters.batches_ok == 0
    assert deframer.counters.records_decoded == 0


# ---------------------------------------------------------------------------
# 01-11 Task 1: the headless ground consumer's own loop, driven in-process
# against a LoopbackLink -- no CLI, no subprocess, just
# `telemetry.ground.cli.run_consumer_loop`.
# ---------------------------------------------------------------------------


def _on_record_collector(records):
    def on_record(**fields):
        records.append(fields)

    return on_record


def _start_ground_loop(link, deframer, db, stop_event, on_record, **kwargs):
    """Runs `run_consumer_loop` on its own thread (it is a plain blocking
    function, not a thread itself -- `main()` owns the only thread it needs
    in production) and returns `(thread, counters)` so a test can both wait
    on decoded output and inspect the counters directly once the thread is
    joined, rather than parsing log text."""
    counters = kwargs.pop("counters", None) or GroundConsumerCounters()
    thread = threading.Thread(
        target=run_consumer_loop,
        kwargs=dict(
            link=link,
            deframer=deframer,
            db=db,
            stop_event=stop_event,
            on_record=on_record,
            counters=counters,
            **kwargs,
        ),
        daemon=True,
        name="test-ground-consumer-loop",
    )
    thread.start()
    return thread, counters


def test_ground_consumer_decodes_batch_to_named_signal_values(dbc, logger_config):
    """The ground consumer's own loop turns a framed batch into a decoded
    signal record carrying the message name, the signal name, its value,
    and its unit taken from the DBC -- compared against the DBC-encoded
    source values, not opaque bytes (GND-01)."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    subject_frame = _build_subject_frame(dbc, timestamp_us=5_000)

    encoder = Encoder(dictionary)
    cfr = encoder.encode(subject_frame, batch_base_timestamp_us=subject_frame.timestamp_us)
    batch_payload = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=subject_frame.timestamp_us,
        batch_seq=0,
        records=[cfr],
    )
    framed = cobs_frame(batch_payload)

    link = LoopbackLink()
    deframer = Deframer(dictionary)
    stop_event = threading.Event()
    records = []
    thread, _counters = _start_ground_loop(
        link,
        deframer,
        dbc,
        stop_event,
        _on_record_collector(records),
        recv_timeout_s=0.05,
        health_interval_s=100.0,
    )
    try:
        link.send(framed)
        deadline = time.monotonic() + 2.0
        while not records and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        stop_event.set()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert len(records) == 1
    record = records[0]
    signal_def = dbc.get_message_by_name(SUBJECT_MESSAGE).get_signal_by_name(
        "Pedal_Press_Percent"
    )
    assert record["message_name"] == SUBJECT_MESSAGE
    assert record["signal"] == "Pedal_Press_Percent"
    assert record["value"] == SUBJECT_SIGNAL_VALUES["Pedal_Press_Percent"]
    assert record["unit"] == signal_def.unit
    assert record["message_id"] == subject_frame.frame_id
    assert record["timestamp_us"] == subject_frame.timestamp_us
    assert record["topic"] == f"/can/{SUBJECT_MESSAGE}"


def test_ground_consumer_counts_undecodable_message_and_continues(dbc, logger_config, caplog):
    """A frame whose message the DBC does not describe is counted as an
    undecodable record and logged once with its id -- and does not stop the
    loop from decoding the next good record in the same batch. Modelled
    directly (T-01-28): the dictionary/CFR layer resolves `id_index`
    against `dbc.messages` and can never itself produce an id absent from
    that same DBC, so this failure is exercised by giving the *decode* step
    a DBC that is missing the subject message while the *dictionary* still
    knows it -- the real-world case this guards is a stale ground DBC after
    a car-side DBC update mid-deployment, not something reachable through
    `telemetry.ground.cli.main()`'s own wiring (which always builds both
    from the same loaded database)."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)

    stripped_db = cantools.database.can.Database(
        messages=[m for m in dbc.messages if m.name != SUBJECT_MESSAGE],
        nodes=dbc.nodes,
        version=dbc.version,
    )

    subject_frame = _build_subject_frame(dbc, timestamp_us=6_000)
    other_frame = _frame_for_message(dbc, OTHER_MESSAGE, timestamp_us=6_000)

    encoder = Encoder(dictionary)
    cfr_subject = encoder.encode(subject_frame, batch_base_timestamp_us=6_000)
    cfr_subject_again = encoder.encode(subject_frame, batch_base_timestamp_us=6_000)
    cfr_other = encoder.encode(other_frame, batch_base_timestamp_us=6_000)
    batch_payload = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=6_000,
        batch_seq=0,
        # the subject message twice, to prove the second occurrence's log
        # is suppressed rather than re-logged (T-01-18-style rate limiting)
        records=[cfr_subject, cfr_subject_again, cfr_other],
    )
    framed = cobs_frame(batch_payload)

    link = LoopbackLink()
    deframer = Deframer(dictionary)
    stop_event = threading.Event()
    records = []
    with caplog.at_level("WARNING"):
        thread, counters = _start_ground_loop(
            link,
            deframer,
            stripped_db,
            stop_event,
            _on_record_collector(records),
            recv_timeout_s=0.05,
            health_interval_s=100.0,
        )
        try:
            link.send(framed)
            deadline = time.monotonic() + 2.0
            while not records and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(0.2)  # let the loop finish processing the whole batch
        finally:
            stop_event.set()
            thread.join(timeout=2.0)

    assert not thread.is_alive()
    # only the "other" message's signals were emitted -- the subject
    # message (appearing twice in this batch) was undecodable both times
    # and the loop kept going regardless.
    assert records, "the loop must continue past undecodable records and still emit the good one"
    assert all(r["message_name"] == OTHER_MESSAGE for r in records)
    assert counters.records_dbc_decode_failed == 2
    assert counters.records_dbc_decode_log_suppressed_count == 1
    assert counters.records_dbc_decoded == 1

    undecodable_logs = [
        r for r in caplog.records if "undecodable record" in r.getMessage()
    ]
    assert len(undecodable_logs) == 1, (
        "the second occurrence of the same frame id must be suppressed, not re-logged"
    )
    assert f"0x{subject_frame.frame_id:X}" in undecodable_logs[0].getMessage()


def test_ground_consumer_discards_corrupt_batch_and_keeps_running(dbc, logger_config):
    """Corrupt batches fed into the loop increment the deframer's counters
    and produce no decoded output at all (LINK-02) -- and the loop itself
    survives to prove it, not merely "would have" (T-01-01)."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    subject_frame = _build_subject_frame(dbc, timestamp_us=8_000)
    encoder = Encoder(dictionary)
    cfr = encoder.encode(subject_frame, batch_base_timestamp_us=8_000)
    batch_payload = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=8_000,
        batch_seq=0,
        records=[cfr],
    )
    framed = bytearray(cobs_frame(batch_payload))
    corrupt_index = len(framed) // 2
    framed[corrupt_index] ^= 0xFF

    link = LoopbackLink()
    deframer = Deframer(dictionary)
    stop_event = threading.Event()
    records = []
    thread, _counters = _start_ground_loop(
        link,
        deframer,
        dbc,
        stop_event,
        _on_record_collector(records),
        recv_timeout_s=0.05,
        health_interval_s=100.0,
    )
    try:
        link.send(bytes(framed))
        time.sleep(0.3)
        assert thread.is_alive(), "the loop must survive a corrupt batch, not just recover afterward"
    finally:
        stop_event.set()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert records == []
    total_corruption = (
        deframer.counters.cobs_failures
        + deframer.counters.crc_failures
        + deframer.counters.batch_format_failures
    )
    assert total_corruption == 1
    assert deframer.counters.batches_ok == 0


def test_ground_consumer_loop_exits_promptly_on_stop_event_with_silent_link(
    dbc, logger_config
):
    """The loop exits on the stop event within a bounded time even when the
    link is silent, so a terminated session does not hang the process
    (T-01-29)."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    link = LoopbackLink()
    deframer = Deframer(dictionary)
    stop_event = threading.Event()
    thread, _counters = _start_ground_loop(
        link,
        deframer,
        dbc,
        stop_event,
        _on_record_collector([]),
        recv_timeout_s=0.1,
        health_interval_s=100.0,
    )
    try:
        time.sleep(0.3)  # let the loop sit idle on a genuinely silent link
        started = time.monotonic()
    finally:
        stop_event.set()
        thread.join(timeout=2.0)
    elapsed = time.monotonic() - started

    assert not thread.is_alive()
    assert elapsed < 1.0, "a silent link must not delay shutdown beyond roughly one recv timeout"


def test_ground_consumer_link_health_reports_batches_and_records(dbc, logger_config, caplog):
    """The consumer's periodic link-health line reports batches received,
    batches discarded by each failure class, records decoded, and records
    that failed to decode."""
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    subject_frame = _build_subject_frame(dbc, timestamp_us=9_000)
    encoder = Encoder(dictionary)
    cfr = encoder.encode(subject_frame, batch_base_timestamp_us=9_000)
    good_batch = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=9_000,
        batch_seq=0,
        records=[cfr],
    )
    good_framed = cobs_frame(good_batch)
    corrupt_framed = bytearray(good_framed)
    corrupt_framed[len(corrupt_framed) // 2] ^= 0xFF

    link = LoopbackLink()
    deframer = Deframer(dictionary)
    stop_event = threading.Event()
    records = []
    with caplog.at_level("INFO"):
        thread, counters = _start_ground_loop(
            link,
            deframer,
            dbc,
            stop_event,
            _on_record_collector(records),
            recv_timeout_s=0.05,
            health_interval_s=0.0,  # force a health line on essentially every iteration
        )
        try:
            link.send(good_framed)
            deadline = time.monotonic() + 2.0
            while not records and time.monotonic() < deadline:
                time.sleep(0.01)
            link.send(bytes(corrupt_framed))
            time.sleep(0.3)
        finally:
            stop_event.set()
            thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert counters.batches_received == 2
    assert counters.records_dbc_decoded == 1
    total_corruption = (
        deframer.counters.cobs_failures
        + deframer.counters.crc_failures
        + deframer.counters.batch_format_failures
    )
    assert total_corruption == 1

    health_lines = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("link-health:")
    ]
    assert health_lines, "at least one link-health line must be logged"
    last = health_lines[-1]
    assert "batches_received=2" in last
    assert "records_decoded=1" in last
    assert "records_decode_failed=0" in last
    assert re.search(r"discarded\[cobs=\d+ crc=\d+ batch_format=\d+", last)
    assert "elapsed_s=" in last


# ---------------------------------------------------------------------------
# 01-11 Task 2: phase success criterion 4, at the process level -- two real
# subprocesses (the car-side logger, the headless ground station) connected
# over one real loopback UDP socket. No radio hardware, no vehicle
# hardware, and no second machine anywhere in this test: two Python
# processes, one loopback interface.
# ---------------------------------------------------------------------------

_LISTENING_RE = re.compile(r"listening on udp://([\d.]+):(\d+)")


def _udp_link_config(*, local_port, remote_host, remote_port):
    return {
        "kind": "udp",
        "udp": {
            "local_host": "127.0.0.1",
            "local_port": local_port,
            "remote_host": remote_host,
            "remote_port": remote_port,
            "recv_bufsize": 8192,
        },
    }


def _write_config(tmp_path, name, link_block, *, telemetry_queue_depth=None):
    config = json.loads((REPO_ROOT / "config" / "logger.json").read_text())
    config["link"] = link_block
    if telemetry_queue_depth is not None:
        config["telemetry"]["queue_depth"] = telemetry_queue_depth
    path = tmp_path / name
    path.write_text(json.dumps(config))
    return path


def _spawn_ground(tmp_path, *, duration_s, health_interval_s=1.0, recv_timeout_s=0.2):
    # remote_port=0: an ephemeral, OS-assigned loopback port -- discovered
    # below by reading the process's own reported listening address, never
    # hardcoded (a fixed port would make this suite fail on any machine
    # where that port happens to be in use). See telemetry.ground.cli's
    # module docstring for why the ground station binds the "remote" half
    # of the shared udp config block, not the "local" half.
    config_path = _write_config(
        tmp_path,
        "ground_logger.json",
        _udp_link_config(local_port=0, remote_host="127.0.0.1", remote_port=0),
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    argv = [
        sys.executable,
        "-u",
        "-m",
        "telemetry.ground.cli",
        "--config",
        str(config_path),
        "--duration-s",
        str(duration_s),
        "--health-interval-s",
        str(health_interval_s),
        "--recv-timeout-s",
        str(recv_timeout_s),
    ]
    return subprocess.Popen(
        argv,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _drain_stream(stream, sink, ready_event=None, ready_holder=None):
    """Continuously reads lines from `stream` into `sink` for as long as
    the process is alive -- run on a background thread so a subprocess's
    stdout/stderr pipe never fills up and blocks the child while the main
    thread is doing something else (waiting for the readiness line, running
    the car process, etc). If `ready_event` is given, sets it the first
    time a line matches `_LISTENING_RE`, storing `(host, port)` in
    `ready_holder`."""
    for line in iter(stream.readline, ""):
        sink.append(line.rstrip("\n"))
        if ready_event is not None and not ready_event.is_set():
            match = _LISTENING_RE.search(line)
            if match:
                ready_holder.append((match.group(1), int(match.group(2))))
                ready_event.set()
    stream.close()


def test_two_process_capture_to_pit_run_over_udp_no_radio_present(tmp_path, dbc, logger_config):
    """Phase success criterion 4, proved at the process level: a frame
    captured by the car-side logger CLI (a real OS subprocess) arrives at
    the headless ground station CLI (a second, separate real OS
    subprocess), decoded against the DBC, having crossed batching, CRC-16,
    COBS, and a real UDP socket -- with messages from both configured
    channels present, the car's archive complete and marked done with zero
    drops, and the ground station's own link-health output reporting zero
    batches discarded on this clean loopback run.

    No radio hardware, no vehicle hardware, and no second machine are
    involved anywhere in this test: two Python processes, one loopback
    network interface (127.0.0.1).
    """
    ground_duration_s = 6.0
    car_duration_s = 3.0

    ground_stdout: list = []
    ground_stderr: list = []
    ready_event = threading.Event()
    ready_holder: list = []

    ground_proc = _spawn_ground(tmp_path, duration_s=ground_duration_s)
    stdout_thread = threading.Thread(
        target=_drain_stream, args=(ground_proc.stdout, ground_stdout), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_drain_stream,
        args=(ground_proc.stderr, ground_stderr, ready_event, ready_holder),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    car_result = None
    try:
        assert ready_event.wait(timeout=10.0), (
            "ground station never reported its bound listening port within 10s "
            f"(stderr so far: {ground_stderr!r})"
        )
        ground_host, ground_port = ready_holder[0]

        # The car sends to the ground process's real, just-discovered
        # bound port -- the ground process is already listening before the
        # car starts sending.
        #
        # telemetry.queue_depth is raised well above the shipped default
        # (1000) for this test's car config specifically: --source
        # synthetic's frames() (telemetry/synth/generator.py) yields an
        # entire duration's worth of events with no real-time pacing at
        # all, so this test's whole allowlisted stream (~2,000 frames for
        # a 3s run) lands in the telemetry deque far faster than
        # TelemetryPipeline can drain, batch, and send it in real time --
        # confirmed directly (a 3s run against the shipped queue_depth=1000
        # measured telemetry_discard_count=288, i.e. drop-oldest evicting
        # ~14% of the allowlisted stream, including all of it for the
        # rarest allowlisted message often enough to flake this assertion).
        # A production run against real hardware paces frames at the bus's
        # own real rate and never approaches this queue depth; this
        # override exists only to make a synthetic-source subprocess test
        # deterministic, not to change any shipped default.
        car_config_path = _write_config(
            tmp_path,
            "car_logger.json",
            _udp_link_config(local_port=0, remote_host=ground_host, remote_port=ground_port),
            telemetry_queue_depth=10_000,
        )

        archive_root = tmp_path / "sessions"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        car_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "telemetry.logger.cli",
                "--config",
                str(car_config_path),
                "--source",
                "synthetic",
                "--archive-root",
                str(archive_root),
                "--duration-s",
                str(car_duration_s),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert car_result.returncode == 0, car_result.stderr
        car_summary = json.loads(car_result.stdout)
        assert car_summary["archive_drops"] == 0
        assert car_summary["archive_marked_done"] is True
        # The raised telemetry.queue_depth (see the config comment above)
        # must actually have eliminated the deque-overflow drops it exists
        # to prevent -- otherwise the two-bus assertion below is just
        # getting lucky.
        assert car_summary["telemetry_discard_count"] == 0

        session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
        assert len(session_dirs) == 1
        assert (session_dirs[0] / ".done").exists()

        # Give the ground process a little more time to receive, decode,
        # and log its final health line after the car has stopped sending.
        time.sleep(1.5)
    finally:
        if ground_proc.poll() is None:
            try:
                ground_proc.wait(timeout=ground_duration_s + 5.0)
            except subprocess.TimeoutExpired:
                ground_proc.kill()
                ground_proc.wait(timeout=5.0)
        stdout_thread.join(timeout=5.0)
        stderr_thread.join(timeout=5.0)

    assert ground_proc.returncode == 0, "\n".join(ground_stderr)

    decoded_records = [json.loads(line) for line in ground_stdout if line.strip()]
    assert decoded_records, "the ground process must have decoded at least one signal record"
    # a substantial, nonzero fraction arrived -- UDP's own unacknowledged
    # loss is a modelled feature of the real radio link, not asserted
    # against here; every transmitted frame arriving is not asserted.
    assert len(decoded_records) > 5

    allowlisted_names = set(
        json.loads((REPO_ROOT / "config" / "logger.json").read_text())["telemetry"]["allowlist"]
    )
    for record in decoded_records:
        assert record["message_name"] in allowlisted_names

    # Two-bus coverage: at least one decoded message belongs to each of
    # config/logger.json's two configured channels. The wire protocol
    # itself carries no per-frame channel field (see telemetry.ground.cli's
    # module docstring), so this is computed here, independently, via the
    # same DBC-derived bus_assignment.by_ecu mapping
    # telemetry.synth.rates.assign_rates already uses for the synthetic
    # generator itself -- not something the ground CLI emits.
    gate_config = load_gate_config(GateConfig.default_path())
    name_to_bus = {r.name: r.bus for r in assign_rates(dbc, gate_config)}
    bus_to_channel = {c.bus: c.name for c in logger_config.channels}
    decoded_channels = {
        bus_to_channel.get(name_to_bus.get(record["message_name"])) for record in decoded_records
    }
    decoded_channels.discard(None)
    assert decoded_channels == set(bus_to_channel.values()), (
        f"expected decoded messages from both configured channels "
        f"({sorted(bus_to_channel.values())}), got {sorted(decoded_channels)}"
    )

    health_lines = [line for line in ground_stderr if "link-health:" in line]
    assert health_lines, "the ground process must log at least one link-health line"
    last_health = health_lines[-1]
    assert "discarded[cobs=0 crc=0 batch_format=0 buffer_overflow=0]" in last_health, last_health
