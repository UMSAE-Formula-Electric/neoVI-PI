"""
Requirements covered: ARCH-02, ARCH-03.

Proves `telemetry.archive.reader.recover_session` against real, deliberately
damaged `.mcap` files, reproducing `01-RESEARCH.md` Pattern 2's verified
result table rather than trusting it from prose. Also pins the library
finding itself (`test_default_mcap_readers_fail_on_a_footerless_file`) so a
later contributor cannot quietly replace `recover_session`'s non-default
reader configuration with the obvious one without a test failing first.

**Scope limit of the kill-based proxy test in this file
(`test_killed_writer_recovers_at_least_every_fsync_confirmed_record`):**
killing a process does not crash the operating system. Any bytes already
handed to `write()` but never `fsync`ed can still survive in the OS page
cache and read back correctly afterward, even when the application's own
fsync logic is completely broken -- the killed process's own in-memory
Python buffers are lost, but the OS is still running underneath it. An
`ArchiveWriter` that never called `fsync` at all could therefore still pass
this test, because the data it "recovers" was never actually at risk of
loss in a mere process kill. What this test proves is write-cadence
correctness: that records make it out of `ArchiveWriter`'s own buffering on
the cadence it claims. Proving fsync correctness -- that those bytes
actually reached durable storage -- needs either dropping the OS page cache
between the kill and the read (requires root, unavailable on this Windows
dev box) or the physical power-pull procedure in `docs/power-pull-test.md`,
which is the real ARCH-03 proof and cannot be waived by a passing proxy
here.
"""

import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcap.exceptions import EndOfFile, RecordLengthLimitExceeded
from mcap.reader import NonSeekingReader, make_reader

from telemetry.archive.reader import recover_session, is_session_complete
from telemetry.archive.session import DONE_FILENAME, MCAP_FILENAME, mark_done, new_session
from telemetry.archive.writer import ArchiveWriter
from telemetry.wire.frame_source import RawFrame

CHANNEL_NAME = "MAIN"
_PAYLOAD_STRUCT = struct.Struct("<I")  # payload encodes the record's own index
CHILD_SCRIPT = Path(__file__).parent / "crash_writer_child.py"


def _make_frame(index: int) -> RawFrame:
    return RawFrame(
        timestamp_us=index,
        frame_id=0x100,
        is_extended=False,
        payload=_PAYLOAD_STRUCT.pack(index),
    )


def _write_uncommitted_session(path, record_count: int, flush_every_records: int = 1):
    """Write `record_count` frames through the real `ArchiveWriter`, then
    simulate a crash by closing the underlying file object directly --
    never calling `ArchiveWriter.close()`/`Writer.finish()`. The resulting
    file has no footer: exactly the state a power-cut file is in.
    `flush_every_records=1` forces every record to reach the OS before the
    simulated crash, so the byte-truncation scenarios below operate on
    fully-written bytes rather than racing Python's own I/O buffering."""
    frames = [_make_frame(i) for i in range(record_count)]
    writer = ArchiveWriter(
        path,
        channel_names=[CHANNEL_NAME],
        flush_every_records=flush_every_records,
        flush_every_s=9999.0,
    )
    for frame in frames:
        writer.add(CHANNEL_NAME, frame)
    writer._f.close()  # simulated crash: never finish(), never ArchiveWriter.close()
    return frames


def _write_committed_session(tmp_path, record_count: int):
    """Write and cleanly close a full session through the real
    `new_session`/`ArchiveWriter`/`mark_done` lifecycle."""
    frames = [_make_frame(i) for i in range(record_count)]
    session = new_session(tmp_path)
    writer = ArchiveWriter(session.mcap_path, channel_names=[CHANNEL_NAME])
    for frame in frames:
        writer.add(CHANNEL_NAME, frame)
    writer.close()
    mark_done(session, writer)
    return session, frames


def test_recovers_all_records_from_a_footerless_file(tmp_path):
    """A file where every record was written but `finish()` was never
    called: nothing is missing, so recovery must return everything."""
    path = tmp_path / "crash.mcap"
    frames = _write_uncommitted_session(path, record_count=50)

    result = recover_session(path)

    assert result.record_count == 50
    assert result.truncated is True
    recovered_frames = [frame for _, frame in result.records]
    assert recovered_frames == frames
    for topic, _ in result.records:
        assert topic == f"/can/{CHANNEL_NAME}"


def test_recovers_a_clean_prefix_from_a_file_truncated_to_half_its_size(tmp_path):
    """Truncating mid-stream must yield a clean prefix -- every returned
    record fully unpacks, and nothing partial is ever emitted."""
    path = tmp_path / "crash.mcap"
    frames = _write_uncommitted_session(path, record_count=50)
    raw = path.read_bytes()

    half_path = tmp_path / "half.mcap"
    half_path.write_bytes(raw[: len(raw) // 2])

    result = recover_session(half_path)

    assert 0 < result.record_count < 50
    assert result.truncated is True
    recovered_frames = [frame for _, frame in result.records]
    assert recovered_frames == frames[: result.record_count]


def test_drops_only_the_record_cut_mid_body(tmp_path):
    """Chopping the final 3 bytes cuts the last record mid-body: recovery
    must drop exactly that one record, not corrupt or fabricate one."""
    path = tmp_path / "crash.mcap"
    frames = _write_uncommitted_session(path, record_count=50)
    raw = path.read_bytes()

    cut_path = tmp_path / "cut.mcap"
    cut_path.write_bytes(raw[:-3])

    result = recover_session(cut_path)

    assert result.record_count == 49
    assert result.truncated is True
    recovered_frames = [frame for _, frame in result.records]
    assert recovered_frames == frames[:49]


def test_recovers_a_complete_session_and_reports_it_not_truncated(tmp_path):
    """A session closed normally (finish() called, footer present) must
    recover everything and report itself as not truncated."""
    session, frames = _write_committed_session(tmp_path, record_count=50)

    result = recover_session(session.mcap_path)

    assert result.record_count == 50
    assert result.truncated is False
    recovered_frames = [frame for _, frame in result.records]
    assert recovered_frames == frames


def test_default_mcap_readers_fail_on_a_footerless_file(tmp_path):
    """Pins `01-RESEARCH.md` Pattern 2's finding directly, so a later
    contributor cannot quietly replace `recover_session`'s non-default
    reader configuration with either "obvious" alternative without a test
    failing first: `mcap.reader.make_reader()` raises a nonsense
    `RecordLengthLimitExceeded` on a footer-less file rather than
    signalling "no footer" cleanly, and `NonSeekingReader(...).iter_messages()`
    called with its own default (`log_time_order=True`) recovers zero of
    fifty complete, uncorrupted records -- silently, because sorting must
    drain the whole stream into memory before yielding anything, and the
    missing footer raises during that drain. Both facts are why
    `recover_session` uses `NonSeekingReader(f).iter_messages(log_time_order=False)`
    and nothing else."""
    path = tmp_path / "crash.mcap"
    _write_uncommitted_session(path, record_count=50)

    with open(path, "rb") as f:
        reader = make_reader(f)
        with pytest.raises(RecordLengthLimitExceeded):
            list(reader.iter_messages())

    recovered_default_order = []
    with open(path, "rb") as f:
        reader = NonSeekingReader(f)
        try:
            for _schema, _channel, message in reader.iter_messages():  # default log_time_order=True
                recovered_default_order.append(message)
        except (EndOfFile, struct.error):
            pass
    assert recovered_default_order == []


def test_is_session_complete_true_with_marker(tmp_path):
    session, _ = _write_committed_session(tmp_path, record_count=1)
    assert is_session_complete(session.directory) is True


def test_is_session_complete_false_without_marker(tmp_path):
    directory = tmp_path / "session"
    directory.mkdir()
    _write_uncommitted_session(directory / MCAP_FILENAME, record_count=1)
    assert is_session_complete(directory) is False


def test_killed_writer_recovers_at_least_every_fsync_confirmed_record(tmp_path):
    """Kill-based proxy test (see this file's module docstring for its
    scope limit): spawn `crash_writer_child.py`, read at least two
    fsync-confirmation lines, then kill the process outright and confirm
    recovery finds at least as many records as the last confirmed fsync
    reported, that every recovered record unpacks, and that the session is
    found with no `.done` marker."""
    env = dict(os.environ)
    src_dir = str(Path(__file__).resolve().parent.parent / "src")
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        [
            sys.executable,
            str(CHILD_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--record-count",
            "5000",
            "--flush-every-records",
            "5",
            "--flush-every-s",
            "60",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    session_dir = None
    fsync_confirmations = []
    deadline = time.monotonic() + 30.0
    try:
        while len(fsync_confirmations) < 2:
            if time.monotonic() > deadline:
                pytest.fail(
                    "crash_writer_child.py did not report two fsync "
                    "confirmations within the test deadline"
                )
            if proc.poll() is not None:
                stderr = proc.stderr.read()
                pytest.fail(
                    f"crash_writer_child.py exited early (code "
                    f"{proc.returncode}): {stderr}"
                )
            line = proc.stdout.readline()
            if not line:
                continue
            line = line.strip()
            if line.startswith("SESSION_DIR:"):
                session_dir = Path(line[len("SESSION_DIR:") :])
            elif line.startswith("FSYNC:"):
                fsync_confirmations.append(int(line[len("FSYNC:") :]))

        # Killing a process does not crash the operating system: bytes
        # already handed to write() but never fsynced can still survive in
        # the OS page cache and read back correctly even if fsync is
        # broken. This kill proves write-cadence correctness only -- see
        # this file's module docstring and docs/power-pull-test.md for the
        # real fsync/durability proof.
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        proc.stdout.close()
        proc.stderr.close()

    assert session_dir is not None, "child never reported its session directory"
    last_confirmed = fsync_confirmations[-1]

    mcap_path = session_dir / MCAP_FILENAME
    result = recover_session(mcap_path)

    assert result.record_count >= last_confirmed
    recovered_indices = [
        _PAYLOAD_STRUCT.unpack(frame.payload)[0] for _, frame in result.records
    ]
    assert recovered_indices == list(range(result.record_count))

    assert not (session_dir / DONE_FILENAME).exists()
    assert is_session_complete(session_dir) is False
