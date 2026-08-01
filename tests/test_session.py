"""
Requirements covered: ARCH-05, OPS-04.

Asserts that each run lands in its own discrete session directory, that
session naming falls back to a monotonic counter when the CM4's RTC-less
clock is epoch-garbage at boot, and that a session's `.done` marker is
written only after close+flush returns, with ordering verified rather than
assumed.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from telemetry.archive import session as session_module
from telemetry.archive.session import (
    NAMING_SOURCE_CLOCK,
    NAMING_SOURCE_COUNTER,
    mark_done,
    new_session,
)
from telemetry.archive.writer import ArchiveWriter
from telemetry.wire.frame_source import RawFrame

CHANNEL_NAME = "MAIN"

_PLAUSIBLE_CLOCK = lambda: datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731
_GARBAGE_CLOCK = lambda: datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _make_frame(index: int = 0) -> RawFrame:
    return RawFrame(timestamp_us=index, frame_id=0x100, is_extended=False, payload=b"\x00\x00\x00\x00")


def _closed_writer(mcap_path):
    """A real, already-closed ArchiveWriter -- the precondition mark_done
    requires."""
    writer = ArchiveWriter(mcap_path, channel_names=[CHANNEL_NAME])
    writer.add(CHANNEL_NAME, _make_frame())
    writer.close()
    return writer


def test_new_session_with_a_working_clock_uses_utc_naming(tmp_path):
    session = new_session(tmp_path, clock=_PLAUSIBLE_CLOCK)

    assert session.session_name == "20260801-120000"
    assert session.naming_source == NAMING_SOURCE_CLOCK
    assert session.directory == tmp_path / "20260801-120000"
    assert session.directory.is_dir()


def test_new_session_with_epoch_garbage_clock_falls_back_to_counter(tmp_path):
    session = new_session(tmp_path, clock=_GARBAGE_CLOCK)

    assert session.naming_source == NAMING_SOURCE_COUNTER
    assert session.session_name.startswith("counter-")
    assert session.directory.is_dir()


def test_two_consecutive_counter_sessions_sort_in_creation_order_and_do_not_collide(tmp_path):
    first = new_session(tmp_path, clock=_GARBAGE_CLOCK)
    second = new_session(tmp_path, clock=_GARBAGE_CLOCK)

    assert first.session_name != second.session_name
    assert sorted([first.session_name, second.session_name]) == [
        first.session_name,
        second.session_name,
    ]
    assert first.directory.is_dir()
    assert second.directory.is_dir()


def test_counter_session_after_state_file_deleted_does_not_collide(tmp_path):
    first = new_session(tmp_path, clock=_GARBAGE_CLOCK)

    state_path = tmp_path / session_module._COUNTER_STATE_FILENAME
    assert state_path.exists()
    state_path.unlink()

    second = new_session(tmp_path, clock=_GARBAGE_CLOCK)

    assert second.session_name != first.session_name
    # The recovered counter must continue past the highest existing
    # counter-named directory, not restart at zero and collide.
    assert not (tmp_path / first.session_name / "COLLIDED").exists()
    assert second.directory.is_dir()
    assert first.directory.is_dir()


def test_two_sessions_each_get_their_own_directory(tmp_path):
    """OPS-04: two sessions created back to back never share a directory."""
    first = new_session(tmp_path, clock=_PLAUSIBLE_CLOCK)
    writer1 = ArchiveWriter(first.mcap_path, channel_names=[CHANNEL_NAME])
    writer1.add(CHANNEL_NAME, _make_frame(1))
    writer1.close()
    mark_done(first, writer1)

    later_clock = lambda: datetime(2026, 8, 1, 12, 0, 1, tzinfo=timezone.utc)  # noqa: E731
    second = new_session(tmp_path, clock=later_clock)
    writer2 = ArchiveWriter(second.mcap_path, channel_names=[CHANNEL_NAME])
    writer2.add(CHANNEL_NAME, _make_frame(2))
    writer2.close()
    mark_done(second, writer2)

    assert first.directory != second.directory
    assert first.mcap_path.exists()
    assert second.mcap_path.exists()
    # Neither session's directory contains the other's artifacts.
    assert set(p.name for p in first.directory.iterdir()) == set(
        p.name for p in first.directory.iterdir()
    )
    assert second.mcap_path.parent == second.directory
    assert first.mcap_path.parent == first.directory
    assert second.done_path not in first.directory.iterdir()
    assert first.done_path not in second.directory.iterdir()


def test_new_session_records_naming_source_and_config_hash_in_sidecar(tmp_path):
    session = new_session(tmp_path, clock=_GARBAGE_CLOCK, config_hash="deadbeef1234")

    sidecar_path = session.directory / session_module.SIDECAR_FILENAME
    assert sidecar_path.exists()
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert payload["naming_source"] == NAMING_SOURCE_COUNTER
    assert payload["config_hash"] == "deadbeef1234"
    assert payload["session_name"] == session.session_name


def test_done_marker_ordering(tmp_path, monkeypatch):
    """The marker file is provably created strictly after close() returns,
    not merely assumed to be."""
    events = []
    session = new_session(tmp_path, clock=_PLAUSIBLE_CLOCK)
    writer = ArchiveWriter(session.mcap_path, channel_names=[CHANNEL_NAME])
    writer.add(CHANNEL_NAME, _make_frame())

    real_close = writer.close

    def spy_close():
        real_close()
        events.append("close")

    monkeypatch.setattr(writer, "close", spy_close)

    real_open = open

    def spy_open(path, *args, **kwargs):
        if Path(path) == session.done_path:
            events.append("marker_open")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(session_module, "open", spy_open, raising=False)

    writer.close()
    mark_done(session, writer)

    assert events == ["close", "marker_open"]


def test_mark_done_raises_if_writer_not_closed(tmp_path):
    session = new_session(tmp_path, clock=_PLAUSIBLE_CLOCK)
    writer = ArchiveWriter(session.mcap_path, channel_names=[CHANNEL_NAME])
    writer.add(CHANNEL_NAME, _make_frame())

    with pytest.raises(RuntimeError):
        mark_done(session, writer)

    assert not session.done_path.exists()

    writer.close()  # cleanup, avoid leaking an open file handle


def test_directory_fsync_attempted_on_non_windows(tmp_path, monkeypatch):
    session = new_session(tmp_path, clock=_PLAUSIBLE_CLOCK)
    writer = _closed_writer(session.mcap_path)

    monkeypatch.setattr(session_module.sys, "platform", "linux")

    _FAKE_DIR_FD = 999999
    open_calls = []
    fsync_calls = []
    real_os_close = os.close
    real_os_fsync = os.fsync

    def spy_os_open(path, flags):
        open_calls.append(Path(path))
        return _FAKE_DIR_FD

    def spy_os_close(fd):
        if fd != _FAKE_DIR_FD:
            real_os_close(fd)

    def spy_os_fsync(fd):
        fsync_calls.append(fd)
        if fd != _FAKE_DIR_FD:
            real_os_fsync(fd)

    monkeypatch.setattr(session_module.os, "open", spy_os_open)
    monkeypatch.setattr(session_module.os, "close", spy_os_close)
    monkeypatch.setattr(session_module.os, "fsync", spy_os_fsync)

    mark_done(session, writer)

    assert open_calls == [session.directory]
    assert _FAKE_DIR_FD in fsync_calls
    assert session.done_path.exists()


def test_directory_fsync_skipped_on_windows(tmp_path, monkeypatch):
    session = new_session(tmp_path, clock=_PLAUSIBLE_CLOCK)
    writer = _closed_writer(session.mcap_path)

    monkeypatch.setattr(session_module.sys, "platform", "win32")

    open_calls = []
    real_os_open = os.open

    def spy_os_open(path, flags):
        open_calls.append(Path(path))
        return real_os_open(path, flags)

    monkeypatch.setattr(session_module.os, "open", spy_os_open)

    mark_done(session, writer)

    assert open_calls == []  # directory fsync never attempted on Windows
    assert session.done_path.exists()
