"""
Requirements covered: CAP-01, CAP-05, CAP-06, OPS-04, OPS-05.
Filled by: 01-10.

Task 1 drives `telemetry.logger.pipeline.TelemetryPipeline` directly against
a real `LoopbackLink` and `Deframer` -- every assertion is about frames that
actually came back out the other end, not internal state.

Task 2 runs `telemetry.logger.cli` as a real subprocess (`python -m
telemetry.logger.cli ...`), following the process-level shape of
`tests/test_measure_cli_smoke.py`, and asserts on its exit code, its
stdout/stderr, and the files it left behind.
"""

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from telemetry.archive.reader import recover_session
from telemetry.capture.fanout import CapturedFrame
from telemetry.framing.cobs_frame import unframe
from telemetry.ground.deframe import Deframer
from telemetry.link.loopback import LoopbackLink
from telemetry.logger.pipeline import TelemetryPipeline
from telemetry.wire.batcher import split_batch
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import MAX_DELTA_T_US, Encoder
from telemetry.wire.frame_source import RawFrame

SUBJECT_MESSAGE = "M195_Pedal_Press_Percent"
SUBJECT_CHANNEL = "MAIN"

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# Task 1: TelemetryPipeline, driven directly.
# ---------------------------------------------------------------------------


def _frame(db, timestamp_us, message_name=SUBJECT_MESSAGE, signal_values=None):
    message = db.get_message_by_name(message_name)
    payload = message.encode(signal_values or {"Pedal_Press_Percent": 0})
    return RawFrame(
        timestamp_us=timestamp_us,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=payload,
    )


def _pipeline(dictionary, telemetry_queue, link, stop_event, **overrides):
    kwargs = dict(
        telemetry_queue=telemetry_queue,
        encoder=Encoder(dictionary),
        link=link,
        dict_version=dictionary.dict_version,
        batch_frames=100,
        batch_max_age_s=10.0,
        stop_event=stop_event,
        poll_timeout_s=0.01,
    )
    kwargs.update(overrides)
    return TelemetryPipeline(**kwargs)


def test_batch_closes_at_configured_frame_count(dbc, logger_config):
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    telemetry_queue = deque()
    link = LoopbackLink()
    stop_event = threading.Event()

    batch_frames = 5
    for i in range(batch_frames):
        telemetry_queue.append(
            CapturedFrame(channel=SUBJECT_CHANNEL, frame=_frame(dbc, 1_000 + i))
        )

    pipeline = _pipeline(
        dictionary, telemetry_queue, link, stop_event, batch_frames=batch_frames
    )
    pipeline.start()
    try:
        received = link.recv(timeout=2.0)
    finally:
        stop_event.set()
        pipeline.join(timeout=2.0)

    assert received is not None
    deframer = Deframer(dictionary)
    batches = list(deframer.feed(received))
    assert len(batches) == 1
    assert len(batches[0]) == batch_frames
    assert deframer.counters.batches_ok == 1


def test_batch_closes_on_age_when_fewer_than_configured_count_have_arrived(
    dbc, logger_config
):
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    telemetry_queue = deque()
    link = LoopbackLink()
    stop_event = threading.Event()

    for i in range(2):
        telemetry_queue.append(
            CapturedFrame(channel=SUBJECT_CHANNEL, frame=_frame(dbc, 1_000 + i))
        )

    pipeline = _pipeline(
        dictionary,
        telemetry_queue,
        link,
        stop_event,
        batch_frames=100,
        batch_max_age_s=0.05,
    )
    pipeline.start()
    try:
        received = link.recv(timeout=2.0)
    finally:
        stop_event.set()
        pipeline.join(timeout=2.0)

    assert received is not None
    deframer = Deframer(dictionary)
    batches = list(deframer.feed(received))
    assert len(batches) == 1
    assert len(batches[0]) == 2


def test_batch_closes_early_on_cfr_window_and_triggering_frame_opens_next_batch(
    dbc, logger_config
):
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    telemetry_queue = deque()
    link = LoopbackLink()
    stop_event = threading.Event()

    frame1 = _frame(dbc, timestamp_us=0)
    frame2 = _frame(dbc, timestamp_us=MAX_DELTA_T_US + 1_000)
    telemetry_queue.append(CapturedFrame(channel=SUBJECT_CHANNEL, frame=frame1))
    telemetry_queue.append(CapturedFrame(channel=SUBJECT_CHANNEL, frame=frame2))

    pipeline = _pipeline(
        dictionary, telemetry_queue, link, stop_event, batch_frames=100
    )
    pipeline.start()
    # frame1 closes when frame2's timestamp is found to fall outside the CFR
    # delta-t window -- that batch arrives while the pipeline is still
    # running. frame2 opens the next batch, which only closes once the stop
    # event flushes the batch in progress.
    first = link.recv(timeout=2.0)
    stop_event.set()
    pipeline.join(timeout=2.0)
    second = link.recv(timeout=2.0)

    assert first is not None
    assert second is not None

    deframer = Deframer(dictionary)
    first_batches = list(deframer.feed(first))
    second_batches = list(deframer.feed(second))

    assert len(first_batches) == 1 and len(first_batches[0]) == 1
    assert len(second_batches) == 1 and len(second_batches[0]) == 1
    assert first_batches[0][0].timestamp_us == frame1.timestamp_us
    assert second_batches[0][0].timestamp_us == frame2.timestamp_us


def test_batch_sequence_numbers_advance_and_wrap_in_order(dbc, logger_config):
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    telemetry_queue = deque()
    link = LoopbackLink()
    stop_event = threading.Event()

    batch_count = 300  # > 256, forcing a wrap of the one-byte batch_seq field
    for i in range(batch_count):
        telemetry_queue.append(
            CapturedFrame(channel=SUBJECT_CHANNEL, frame=_frame(dbc, 1_000 * i))
        )

    pipeline = _pipeline(
        dictionary, telemetry_queue, link, stop_event, batch_frames=1
    )
    pipeline.start()

    seqs = []
    for _ in range(batch_count):
        received = link.recv(timeout=2.0)
        assert received is not None
        # `received` is exactly what `frame()` produced: the COBS-encoded
        # segment plus its trailing 0x00 delimiter. `unframe`'s contract is
        # the delimiter already stripped (that stripping is normally
        # Deframer.feed's job), so strip it here for this direct,
        # header-inspecting check.
        header, records = split_batch(unframe(received[:-1]))
        assert len(records) == 1
        seqs.append(header.batch_seq)

    stop_event.set()
    pipeline.join(timeout=2.0)

    assert seqs == [i % 256 for i in range(batch_count)]


def test_encoder_rejections_counted_logged_with_context_and_skipped(
    dbc, logger_config, caplog
):
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    telemetry_queue = deque()
    link = LoopbackLink()
    stop_event = threading.Event()

    known_message = dbc.get_message_by_name(SUBJECT_MESSAGE)
    bogus_frame_id = max(fid for fid, _ in dictionary.index) + 1000
    assert (bogus_frame_id, False) not in dictionary.index

    unknown_frame = RawFrame(
        timestamp_us=1_000, frame_id=bogus_frame_id, is_extended=False, payload=b"\x01"
    )
    too_long_frame = RawFrame(
        timestamp_us=2_000,
        frame_id=known_message.frame_id,
        is_extended=known_message.is_extended_frame,
        payload=b"\x00" * 9,
    )
    good_frame = _frame(dbc, timestamp_us=3_000)

    telemetry_queue.append(CapturedFrame(channel=SUBJECT_CHANNEL, frame=unknown_frame))
    telemetry_queue.append(CapturedFrame(channel=SUBJECT_CHANNEL, frame=too_long_frame))
    telemetry_queue.append(CapturedFrame(channel=SUBJECT_CHANNEL, frame=good_frame))

    pipeline = _pipeline(dictionary, telemetry_queue, link, stop_event, batch_frames=100)
    with caplog.at_level("WARNING"):
        pipeline.start()
        time.sleep(0.2)
        stop_event.set()
        pipeline.join(timeout=2.0)

    assert pipeline.counters.unknown_id_count == 1
    assert pipeline.counters.payload_too_long_count == 1
    assert pipeline.counters.frames_sent == 1

    received = link.recv(timeout=1.0)
    assert received is not None
    deframer = Deframer(dictionary)
    batches = list(deframer.feed(received))
    assert len(batches) == 1
    assert len(batches[0]) == 1
    assert batches[0][0].frame_id == good_frame.frame_id

    joined = " ".join(r.message for r in caplog.records)
    assert f"0x{bogus_frame_id:X}" in joined
    assert f"0x{known_message.frame_id:X}" in joined


class _RaisingLink:
    """A `Link` whose `send` always raises -- proves T-01-26: a transmit
    failure must never propagate into the capture or archive path."""

    def send(self, data: bytes) -> None:
        raise RuntimeError("simulated transmit failure")

    def recv(self, timeout=None):
        return None

    def close(self) -> None:
        pass


def test_link_send_failure_counted_logged_and_pipeline_continues(
    dbc, logger_config, caplog
):
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    telemetry_queue = deque()
    link = _RaisingLink()
    stop_event = threading.Event()

    for i in range(3):
        telemetry_queue.append(
            CapturedFrame(channel=SUBJECT_CHANNEL, frame=_frame(dbc, 1_000 + i))
        )

    pipeline = _pipeline(dictionary, telemetry_queue, link, stop_event, batch_frames=1)
    with caplog.at_level("WARNING"):
        pipeline.start()
        time.sleep(0.2)
        stop_event.set()
        pipeline.join(timeout=2.0)

    assert not pipeline.thread.is_alive()
    assert pipeline.counters.link_send_failure_count == 3
    assert pipeline.counters.batches_sent == 0
    assert pipeline.counters.frames_sent == 3


def test_stop_event_flushes_batch_in_progress(dbc, logger_config):
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    telemetry_queue = deque()
    link = LoopbackLink()
    stop_event = threading.Event()

    telemetry_queue.append(
        CapturedFrame(channel=SUBJECT_CHANNEL, frame=_frame(dbc, 1_000))
    )

    pipeline = _pipeline(dictionary, telemetry_queue, link, stop_event, batch_frames=100)
    pipeline.start()
    time.sleep(0.1)  # let the pipeline drain the one queued frame into its batch
    stop_event.set()
    pipeline.join(timeout=2.0)

    received = link.recv(timeout=1.0)
    assert received is not None
    deframer = Deframer(dictionary)
    batches = list(deframer.feed(received))
    assert len(batches) == 1
    assert len(batches[0]) == 1


def test_pipeline_reports_frames_batches_and_bytes_sent(dbc, logger_config):
    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    telemetry_queue = deque()
    link = LoopbackLink()
    stop_event = threading.Event()

    for i in range(4):
        telemetry_queue.append(
            CapturedFrame(channel=SUBJECT_CHANNEL, frame=_frame(dbc, 1_000 + i))
        )

    pipeline = _pipeline(dictionary, telemetry_queue, link, stop_event, batch_frames=2)
    pipeline.start()
    first = link.recv(timeout=2.0)
    second = link.recv(timeout=2.0)
    stop_event.set()
    pipeline.join(timeout=2.0)

    assert first is not None and second is not None
    assert pipeline.counters.frames_sent == 4
    assert pipeline.counters.batches_sent == 2
    assert pipeline.counters.bytes_sent == len(first) + len(second)


# ---------------------------------------------------------------------------
# Task 2: the car-side CLI, run as a real subprocess.
# ---------------------------------------------------------------------------


def _run_cli(archive_root, *extra_args, config_path=None, duration_s=1.0):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    argv = [
        sys.executable,
        "-m",
        "telemetry.logger.cli",
        "--source",
        "synthetic",
        "--archive-root",
        str(archive_root),
        "--duration-s",
        str(duration_s),
    ]
    if config_path is not None:
        argv += ["--config", str(config_path)]
    argv += list(extra_args)
    return subprocess.run(
        argv, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=60
    )


def test_cli_synthetic_run_exits_zero_with_a_complete_session(tmp_path):
    result = _run_cli(tmp_path)

    assert result.returncode == 0, result.stderr

    session_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]

    mcap_files = list(session_dir.glob("*.mcap"))
    assert len(mcap_files) == 1
    assert mcap_files[0].stat().st_size > 0
    assert (session_dir / ".done").exists()
    assert (session_dir / "session.json").exists()

    recovered = recover_session(mcap_files[0])
    assert recovered.record_count > 0
    assert not recovered.truncated


def test_cli_stdout_summary_parses_as_json_and_reports_expected_fields(tmp_path):
    result = _run_cli(tmp_path)

    assert result.returncode == 0, result.stderr

    summary = json.loads(result.stdout)
    assert summary["archive_drops"] == 0
    assert summary["frames_captured"] > 0
    assert summary["frames_archived"] > 0
    assert "archive_high_water_mark" in summary
    assert "telemetry_high_water_mark" in summary
    assert summary["archive_marked_done"] is True


def test_cli_two_consecutive_runs_produce_two_distinct_session_directories(tmp_path):
    first = _run_cli(tmp_path)
    assert first.returncode == 0, first.stderr
    # UTC session names are second-resolution; force the two runs into
    # different seconds so this test asserts OPS-04 rather than racing the
    # clock.
    time.sleep(1.1)
    second = _run_cli(tmp_path)
    assert second.returncode == 0, second.stderr

    session_dirs = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert len(session_dirs) == 2
    assert session_dirs[0] != session_dirs[1]


def test_cli_unknown_config_key_exits_nonzero_and_creates_no_session(tmp_path):
    config_data = json.loads((REPO_ROOT / "config" / "logger.json").read_text())
    config_data["unexpected_key"] = "nope"
    bad_config_path = tmp_path / "bad_logger.json"
    bad_config_path.write_text(json.dumps(config_data))

    archive_root = tmp_path / "sessions"
    result = _run_cli(archive_root, config_path=bad_config_path)

    assert result.returncode != 0
    assert "unexpected_key" in result.stderr
    assert not archive_root.exists()


def test_cli_archive_root_override_takes_effect_other_fields_unchanged(tmp_path):
    archive_root = tmp_path / "custom_sessions"
    result = _run_cli(archive_root)

    assert result.returncode == 0, result.stderr
    session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1

    summary = json.loads(result.stdout)
    assert Path(summary["session_dir"]).resolve().parent == archive_root.resolve()
    # link.kind was never overridden -- it must still be config/logger.json's
    # own configured value ("loopback"), proving the override touched only
    # the field it named.
    assert summary["link_kind"] == "loopback"


def test_cli_missing_config_path_exits_nonzero_naming_the_path(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    result = _run_cli(tmp_path / "sessions", config_path=missing_path)

    assert result.returncode != 0
    assert str(missing_path) in result.stderr


def test_cli_archive_overflow_leaves_no_done_marker_and_exits_nonzero(tmp_path):
    """CR-01 regression: CAP-03 treats a full archive queue as fatal
    ("archive queue never drops... a full queue is fatal"), and ARCH-05's
    whole contract for `.done` is that its presence means the archive is
    complete and trustworthy. A session that structurally lost a frame to
    `archive_overflow` must never be left with a `.done` marker or a zero
    exit code, even though the `ArchiveWriter` itself never saw an I/O
    failure and closes cleanly. `archive.queue_depth=1` plus
    `flush_every_records=1` (an fsync on every record) makes the archive
    consumer thread reliably slower than the synthetic capture loop
    producing frames, so the second frame submitted overflows the queue
    deterministically rather than racily.
    """
    config_data = json.loads((REPO_ROOT / "config" / "logger.json").read_text())
    config_data["archive"]["queue_depth"] = 1
    config_data["archive"]["flush_every_records"] = 1
    overflow_config_path = tmp_path / "overflow_logger.json"
    overflow_config_path.write_text(json.dumps(config_data))

    archive_root = tmp_path / "sessions"
    result = _run_cli(
        archive_root, config_path=overflow_config_path, duration_s=1.0
    )

    assert result.returncode != 0, result.stderr

    session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]
    assert not (session_dir / ".done").exists()

    summary = json.loads(result.stdout)
    assert summary["archive_overflow"] is True
    assert summary["archive_write_failure"] is False
    assert summary["archive_marked_done"] is False
