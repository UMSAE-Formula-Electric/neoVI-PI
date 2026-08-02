"""
Requirements covered: ARCH-01, ARCH-05, CAP-03, CAP-04, LINK-01, LINK-02,
LINK-03, LINK-04, GND-01, OPS-04.

The 01-04 tracer: one CAN frame travels the complete Phase 1 path, end to
end, with production code at every layer — capture fan-out -> MCAP archive
on disk, and in parallel capture fan-out -> allowlist filter -> CFR encode
-> batch -> CRC-16 -> COBS -> Link -> deframe -> CFR decode -> DBC decode.
No radio, no vehicle hardware, and no network socket anywhere in this
chain — `LoopbackLink` is the only transport involved.

01-11 Task 1 widens this file with in-process tests of
`telemetry.ground.cli.run_consumer_loop` — the headless ground station's
own receive-decode-emit loop, driven directly against a `LoopbackLink`, no
CLI or subprocess involved. Task 2 (a later commit) adds the phase's own
process-level proof over a real UDP socket.

`01-05` through `01-13` build outward from this slice; this file is the
proof that the whole spine holds together on one frame before any of that
widening starts.
"""

import re
import threading
import time

import cantools

from telemetry.archive.session import mark_done, new_session
from telemetry.archive.writer import ArchiveWriter
from telemetry.capture.fanout import CapturedFrame, FanOut
from telemetry.framing.cobs_frame import frame as cobs_frame
from telemetry.ground.cli import GroundConsumerCounters, run_consumer_loop
from telemetry.ground.deframe import Deframer
from telemetry.link.loopback import LoopbackLink
from telemetry.logger.config import resolve_allowlist
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
