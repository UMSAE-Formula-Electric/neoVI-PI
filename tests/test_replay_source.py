"""
Requirements covered: ARCH-01, CAP-01, OPS-05, and the Phase 0 D-14
real-traffic re-check named in `00-DECISION.md`'s worst-case-bracket
section.

Task 1 proves `ArchiveReplaySource` — a captured session archive replayed
as a `FrameSource` — round-trips byte-identically, tags frames with their
archived channel, honours a channel filter, replays a crashed session's
complete records, structurally satisfies `FrameSource`, feeds
`Encoder.encode` unmodified, and reports measured per-channel frame rates
from the archive's own timestamps.

Task 2 proves the measurement CLI's real-log input path: run against a
small real archive, the report is keyed under a single measured bracket
with provenance naming the archive and session, achieved-fps figures come
from the archive's own timestamps, and the existing synthetic default path
(no `--frame-source archive` flag) is unaffected.

Every archive fixture below is written through the real `ArchiveWriter` /
`new_session` / `mark_done` lifecycle, and every frame carries a real DBC
message's frame_id and DLC-correct payload, so the round trip is proven
against the format `ArchiveWriter` actually produces and every frame is
guaranteed encodable — never a hand-built `.mcap` file or an off-DBC id.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from telemetry.archive.session import mark_done, new_session
from telemetry.archive.writer import ArchiveWriter
from telemetry.capture.fanout import CapturedFrame
from telemetry.capture.replay_source import ArchiveReplaySource
from telemetry.measure import cli
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import Encoder
from telemetry.wire.frame_source import RawFrame

CHANNEL_A = "MAIN"
CHANNEL_B = "SENSOR"
MESSAGE_A_NAME = "M176_Fast_Info"
MESSAGE_B_NAME = "M192_Command_Message"


def _dbc_frame(message, index: int, base_timestamp_us: int = 0, step_us: int = 1000) -> RawFrame:
    """A real DBC message's frame_id/DLC with a payload that varies by
    `index`, so a round-trip test can catch a dropped or swapped record
    rather than passing by coincidence."""
    length = message.length
    payload = bytes((index + b) % 256 for b in range(length))
    return RawFrame(
        timestamp_us=base_timestamp_us + index * step_us,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=payload,
    )


def _write_two_channel_session(root_dir, dbc, frame_count: int = 200):
    """Writes `frame_count` frames alternating across CHANNEL_A/CHANNEL_B,
    each a real DBC message, through the real `ArchiveWriter` and
    `mark_done` lifecycle (finish() called, .done marker present)."""
    message_a = dbc.get_message_by_name(MESSAGE_A_NAME)
    message_b = dbc.get_message_by_name(MESSAGE_B_NAME)

    session = new_session(root_dir)
    writer = ArchiveWriter(session.mcap_path, channel_names=[CHANNEL_A, CHANNEL_B])

    expected = []
    for i in range(frame_count):
        if i % 2 == 0:
            channel, message = CHANNEL_A, message_a
        else:
            channel, message = CHANNEL_B, message_b
        frame = _dbc_frame(message, i)
        writer.add(channel, frame)
        expected.append(CapturedFrame(channel=channel, frame=frame))

    writer.close()
    mark_done(session, writer)
    return session, expected


# ---------------------------------------------------------------------------
# Task 1: ArchiveReplaySource
# ---------------------------------------------------------------------------


def test_frames_round_trip_byte_identically_in_order(tmp_path, dbc):
    session, expected = _write_two_channel_session(tmp_path, dbc, frame_count=200)

    source = ArchiveReplaySource(session.mcap_path)
    frames = list(source.frames())

    assert frames == [captured.frame for captured in expected]


def test_captured_frames_tag_channel_recovered_from_topic(tmp_path, dbc):
    session, expected = _write_two_channel_session(tmp_path, dbc, frame_count=200)

    source = ArchiveReplaySource(session.mcap_path)
    captured = list(source.captured_frames())

    assert captured == expected


def test_channel_filter_narrows_without_altering_yielded_frames(tmp_path, dbc):
    session, expected = _write_two_channel_session(tmp_path, dbc, frame_count=200)

    source = ArchiveReplaySource(session.mcap_path, channel_filter=[CHANNEL_A])
    captured = list(source.captured_frames())

    expected_a = [item for item in expected if item.channel == CHANNEL_A]
    assert captured == expected_a
    assert captured  # the fixture always writes some CHANNEL_A frames
    assert all(item.channel == CHANNEL_A for item in captured)


def test_crashed_session_replays_its_complete_records(tmp_path, dbc):
    """`finish()` deliberately never called -- the resulting file has no
    footer, exactly the state a power-cut file is in. Every record was
    fully written (flush_every_records=1 forces each to reach the OS
    before the simulated crash), so nothing here is actually incomplete;
    the point is that ArchiveReplaySource reads through the recovery path
    rather than a reader that assumes a complete file."""
    message = dbc.get_message_by_name(MESSAGE_A_NAME)
    path = tmp_path / "crash.mcap"
    writer = ArchiveWriter(
        path, channel_names=[CHANNEL_A], flush_every_records=1, flush_every_s=9999.0
    )

    expected = [_dbc_frame(message, i) for i in range(50)]
    for frame in expected:
        writer.add(CHANNEL_A, frame)
    writer._f.close()  # simulated crash: never finish(), never ArchiveWriter.close()

    source = ArchiveReplaySource(path)
    frames = list(source.frames())

    assert frames == expected
    assert source.truncated is True
    assert source.record_count == 50


def test_satisfies_frame_source_protocol_structurally(tmp_path, dbc):
    """`FrameSource` is a `Protocol` with exactly one required method,
    `frames() -> Iterator[RawFrame]` -- proven structurally (the method
    exists, is callable, and yields `RawFrame`s) rather than by
    `isinstance`, since the protocol is not `@runtime_checkable`."""
    session, _ = _write_two_channel_session(tmp_path, dbc, frame_count=10)
    source = ArchiveReplaySource(session.mcap_path)

    assert hasattr(source, "frames") and callable(source.frames)
    frames = list(source.frames())
    assert frames
    assert all(isinstance(frame, RawFrame) for frame in frames)


def test_frames_feed_encoder_encode_without_modification(tmp_path, dbc):
    """The whole point of the D-08 interface: the encoder needs no change
    to consume a replayed archive."""
    session, _ = _write_two_channel_session(tmp_path, dbc, frame_count=20)
    source = ArchiveReplaySource(session.mcap_path)

    dictionary = build_id_dictionary(dbc, dbc_path=None)
    encoder = Encoder(dictionary)

    frames = list(source.frames())
    base_timestamp_us = frames[0].timestamp_us
    for frame in frames:
        cfr = encoder.encode(frame, base_timestamp_us)
        assert isinstance(cfr, bytes)
        assert len(cfr) > 0


def test_measured_frame_rates_come_from_archive_timestamps(tmp_path, dbc):
    session, expected = _write_two_channel_session(tmp_path, dbc, frame_count=200)
    source = ArchiveReplaySource(session.mcap_path)

    rates = source.measured_frame_rates_hz()

    all_timestamps = [item.frame.timestamp_us for item in expected]
    span_s = (max(all_timestamps) - min(all_timestamps)) / 1_000_000.0
    expected_total_rate = len(expected) / span_s

    assert set(rates) == {CHANNEL_A, CHANNEL_B}
    assert all(rate > 0 for rate in rates.values())
    assert sum(rates.values()) == pytest.approx(expected_total_rate)


def test_measured_frame_rates_empty_archive_reports_zero(tmp_path):
    path = tmp_path / "empty.mcap"
    writer = ArchiveWriter(path, channel_names=[CHANNEL_A])
    writer.close()

    source = ArchiveReplaySource(path)
    assert source.measured_frame_rates_hz() == {}


# ---------------------------------------------------------------------------
# Task 2: the compression gate's real-log input path (D-14 discharge)
# ---------------------------------------------------------------------------


def _run_cli_subprocess(repo_root: Path, out_dir: Path, *extra_args):
    """Runs the measurement CLI as a real subprocess (not `cli.main()`
    in-process) so this exercises the same command line a person -- or the
    Phase 1 first bench/track session -- would actually type."""
    src_dir = str(repo_root / "src")
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    args = [
        sys.executable,
        "-m",
        "telemetry.measure.cli",
        "--out-dir",
        str(out_dir),
        *extra_args,
    ]
    return subprocess.run(args, cwd=str(repo_root), env=env, capture_output=True, text=True)


def test_archive_frame_source_produces_a_measured_bracket_report(tmp_path, dbc, repo_root):
    session, expected = _write_two_channel_session(tmp_path, dbc, frame_count=60)

    result = _run_cli_subprocess(
        repo_root,
        tmp_path / "out",
        "--frame-source",
        "archive",
        "--archive-path",
        str(session.mcap_path),
    )
    assert result.returncode == 0, result.stderr

    report = json.loads((tmp_path / "out" / cli.REPORT_JSON_FILENAME).read_text())

    assert set(report["brackets"]) == {"measured"}
    measured = report["brackets"]["measured"]
    assert measured["aggregate"]["frame_count"] == len(expected)
    assert measured["aggregate"]["clean_bytes_per_frame"] > 0


def test_archive_report_provenance_names_archive_and_session_not_synthetic(tmp_path, dbc, repo_root):
    session, _ = _write_two_channel_session(tmp_path, dbc, frame_count=60)

    result = _run_cli_subprocess(
        repo_root,
        tmp_path / "out",
        "--frame-source",
        "archive",
        "--archive-path",
        str(session.mcap_path),
    )
    assert result.returncode == 0, result.stderr

    report = json.loads((tmp_path / "out" / cli.REPORT_JSON_FILENAME).read_text())
    meta = report["meta"]

    assert str(session.mcap_path.resolve()) in meta["input_provenance"]
    assert session.session_name in meta["input_provenance"]
    assert "SyntheticFrameSource" not in meta["input_provenance"]
    assert "synthesized" not in meta["input_provenance"]
    assert "not a modelled stream" in meta["input_provenance"]

    # T-01-30: a report that measured captured traffic must never carry the
    # synthetic-stream input-provenance caveat ("this is a modelled stream,
    # not a captured vehicle log") or the synthetic-entropy limitation text
    # that belongs to a modelled report -- checked verbatim rather than by
    # banning the word "synthetic" outright, since the real-log limitation
    # text legitimately still names the synthetic model for comparison.
    assert "this is a modelled stream, not a captured vehicle log" not in meta["input_provenance"]
    assert "synthetic data has only the entropy" not in meta["known_limitation"]
    assert "one recorded session" in meta["known_limitation"].lower()


def test_archive_report_achieved_fps_from_archive_timestamps(tmp_path, dbc, repo_root):
    session, expected = _write_two_channel_session(tmp_path, dbc, frame_count=200)

    result = _run_cli_subprocess(
        repo_root,
        tmp_path / "out",
        "--frame-source",
        "archive",
        "--archive-path",
        str(session.mcap_path),
    )
    assert result.returncode == 0, result.stderr

    report = json.loads((tmp_path / "out" / cli.REPORT_JSON_FILENAME).read_text())
    meta = report["meta"]

    source = ArchiveReplaySource(session.mcap_path)
    expected_rates = source.measured_frame_rates_hz()

    assert meta["achieved_bus_fps"] == pytest.approx(expected_rates)
    assert meta["duration_s_source"] == "archive_measured"


def test_default_synthetic_path_unchanged_by_a_missing_frame_source_flag(monkeypatch, tmp_path):
    """The existing 00-06 smoke-test acceptance criterion, pinned so it
    cannot regress unseen: a run with no `--frame-source` flag at all still
    produces the three modelled brackets."""
    argv = [
        "telemetry.measure.cli",
        "--only-message",
        "M192_Command_Message",
        "--duration-s",
        "1",
        "--out-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr("sys.argv", argv)
    cli.main()

    report = json.loads((tmp_path / cli.REPORT_JSON_FILENAME).read_text())
    from telemetry.synth.entropy import BRACKET_NAMES

    assert set(report["brackets"]) == set(BRACKET_NAMES)
    assert "synthesized" in report["meta"]["input_provenance"]


def test_archive_frame_source_without_archive_path_exits_nonzero(monkeypatch, tmp_path, capsys):
    argv = [
        "telemetry.measure.cli",
        "--frame-source",
        "archive",
        "--out-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert not (tmp_path / cli.REPORT_JSON_FILENAME).exists()
    assert "--archive-path" in capsys.readouterr().err
