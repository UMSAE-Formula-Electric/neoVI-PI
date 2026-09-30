"""
Task 2's behaviour-first hardening pass for 03-01 (OPS-02): pins the status
file's failure modes -- atomicity, reboot-boundary staleness, and
malformed-content handling -- as isolated assertions, separate from
`tests/test_ops_tracer.py`'s end-to-end proof. Every time comparison uses
an injected `now_fn`, never `time.sleep` (`telemetry.ground.cli`'s
established `now_fn: Callable[[], float] = time.monotonic` seam). The
concurrent-read test is the only one using real threads, and it is bounded
by a fixed write count, never a wall-clock sleep.
"""

import json
import os
import threading
from pathlib import Path

import pytest

from telemetry.ops import heartbeat as heartbeat_module
from telemetry.ops.heartbeat import (
    HeartbeatPublisher,
    HeartbeatReadError,
    HeartbeatSnapshot,
    read_heartbeat,
    write_heartbeat,
)

_WRITE_COUNT = 200


# ---------------------------------------------------------------------------
# Atomic write: a concurrent reader never observes a torn/partial write.
# ---------------------------------------------------------------------------


def test_concurrent_reader_never_observes_torn_or_incomplete_json(tmp_path):
    path = tmp_path / "status.json"
    stop_writing = threading.Event()
    write_errors = []
    read_errors = []

    def _writer():
        try:
            for i in range(_WRITE_COUNT):
                write_heartbeat(
                    path,
                    HeartbeatSnapshot(state="capturing", detail=None, extras={"i": i}),
                )
        except Exception as exc:  # pragma: no cover -- surfaced via assertion below
            write_errors.append(exc)
        finally:
            stop_writing.set()

    def _reader():
        while not stop_writing.is_set():
            try:
                raw = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                # Tolerated only before the writer's first write has landed.
                continue
            except PermissionError:
                # Windows-only: NTFS momentarily denies opening the
                # destination during `os.replace`'s rename window --
                # observed live on this dev box, not the POSIX atomicity
                # guarantee under test (the module docstring already
                # scopes that guarantee to Linux, the deployment target,
                # where no such lock window exists). This is a transient
                # "try again", never a torn/partial read.
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                read_errors.append(exc)
                continue
            if "state" not in payload:
                read_errors.append(
                    AssertionError(f"payload missing required key 'state': {payload!r}")
                )

    writer_thread = threading.Thread(target=_writer)
    reader_thread = threading.Thread(target=_reader)
    reader_thread.start()
    writer_thread.start()
    writer_thread.join(timeout=30)
    reader_thread.join(timeout=30)

    assert not write_errors, write_errors
    assert not read_errors, read_errors


def test_write_heartbeat_leaves_no_tmp_sibling(tmp_path):
    path = tmp_path / "status.json"
    write_heartbeat(path, HeartbeatSnapshot(state="capturing", detail=None, extras={}))

    siblings = list(tmp_path.iterdir())
    assert siblings == [path]
    assert not list(tmp_path.glob("*.tmp-*"))


def test_temp_file_is_created_in_the_targets_own_directory(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    captured = {}
    real_replace = os.replace

    def _spy_replace(src, dst):
        captured["src_parent"] = Path(src).parent
        return real_replace(src, dst)

    monkeypatch.setattr(heartbeat_module.os, "replace", _spy_replace)

    write_heartbeat(path, HeartbeatSnapshot(state="capturing", detail=None, extras={}))

    assert "src_parent" in captured
    assert captured["src_parent"] == tmp_path


# ---------------------------------------------------------------------------
# Staleness: the reboot-boundary regression, the implausible-age bound, and
# the ordinary threshold boundary.
# ---------------------------------------------------------------------------


def _write_raw_heartbeat(path, **fields):
    payload = {"state": "capturing", "written_at_monotonic": 0.0}
    payload.update(fields)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_written_at_greater_than_now_is_stale_clock_went_backwards(tmp_path):
    path = tmp_path / "status.json"
    _write_raw_heartbeat(path, written_at_monotonic=1_000.0)

    reading = read_heartbeat(path, stale_after_s=5.0, now_fn=lambda: 500.0)

    assert reading.stale is True
    assert reading.staleness_reason == "clock-went-backwards"


def test_age_far_beyond_implausible_constant_is_stale_implausible_age(tmp_path):
    path = tmp_path / "status.json"
    _write_raw_heartbeat(path, written_at_monotonic=0.0)

    reading = read_heartbeat(
        path, stale_after_s=5.0, now_fn=lambda: heartbeat_module._IMPLAUSIBLE_AGE_S * 2
    )

    assert reading.stale is True
    assert reading.staleness_reason == "implausible-age"


def test_age_between_interval_and_stale_after_s_is_fresh(tmp_path):
    path = tmp_path / "status.json"
    _write_raw_heartbeat(path, written_at_monotonic=100.0)

    # interval_s (implied 1.0) < age (3.0) < stale_after_s (5.0)
    reading = read_heartbeat(path, stale_after_s=5.0, now_fn=lambda: 103.0)

    assert reading.stale is False
    assert reading.staleness_reason is None


def test_age_just_past_stale_after_s_is_stale(tmp_path):
    path = tmp_path / "status.json"
    _write_raw_heartbeat(path, written_at_monotonic=100.0)

    reading = read_heartbeat(path, stale_after_s=5.0, now_fn=lambda: 105.001)

    assert reading.stale is True
    assert reading.staleness_reason == "stale"


# ---------------------------------------------------------------------------
# read_heartbeat never guesses at malformed or absent content.
# ---------------------------------------------------------------------------


def test_read_heartbeat_missing_file_raises(tmp_path):
    with pytest.raises(HeartbeatReadError):
        read_heartbeat(tmp_path / "does_not_exist.json", stale_after_s=5.0)


def test_read_heartbeat_non_json_bytes_raises(tmp_path):
    path = tmp_path / "status.json"
    path.write_bytes(b"not json at all")

    with pytest.raises(HeartbeatReadError):
        read_heartbeat(path, stale_after_s=5.0)


def test_read_heartbeat_missing_state_key_raises(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"written_at_monotonic": 1.0}), encoding="utf-8")

    with pytest.raises(HeartbeatReadError, match="state"):
        read_heartbeat(path, stale_after_s=5.0)


def test_read_heartbeat_missing_written_at_monotonic_key_raises(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"state": "capturing"}), encoding="utf-8")

    with pytest.raises(HeartbeatReadError, match="written_at_monotonic"):
        read_heartbeat(path, stale_after_s=5.0)


# ---------------------------------------------------------------------------
# HeartbeatPublisher.remove() tolerates an already-absent file.
# ---------------------------------------------------------------------------


def test_publisher_remove_on_already_absent_file_does_not_raise(tmp_path):
    path = tmp_path / "status.json"
    publisher = HeartbeatPublisher(
        path=path,
        interval_s=1.0,
        stop_event=threading.Event(),
        snapshot_fn=lambda: HeartbeatSnapshot(state="capturing", detail=None, extras={}),
    )

    assert not path.exists()
    publisher.remove()  # must not raise
    assert not path.exists()


# ---------------------------------------------------------------------------
# LED indicator seam (03-03, OPS-02): every write drives an indicator; a
# raising indicator never takes down the status file or the publisher.
# ---------------------------------------------------------------------------


class _RecordingLed:
    """Test double: records every `set_state` argument and counts `close()`
    calls -- never touches real hardware."""

    def __init__(self):
        self.states = []
        self.close_count = 0

    def set_state(self, state):
        self.states.append(state)

    def close(self):
        self.close_count += 1


class _RaisingLed:
    """Test double whose `set_state` always raises -- pins that a broken
    physical indicator can never take the status file or the publisher
    thread down with it."""

    def __init__(self):
        self.close_count = 0

    def set_state(self, state):
        raise RuntimeError("simulated led failure")

    def close(self):
        self.close_count += 1


def test_publisher_without_led_uses_null_led_indicator_by_default(tmp_path):
    path = tmp_path / "status.json"
    publisher = HeartbeatPublisher(
        path=path,
        interval_s=1.0,
        stop_event=threading.Event(),
        snapshot_fn=lambda: HeartbeatSnapshot(state="capturing", detail=None, extras={}),
    )

    # Must not raise -- the default NullLedIndicator is silently driven.
    publisher.publish_now(publisher.snapshot_fn())
    assert path.exists()


def test_publish_now_calls_set_state_with_the_written_state(tmp_path):
    path = tmp_path / "status.json"
    led = _RecordingLed()
    publisher = HeartbeatPublisher(
        path=path,
        interval_s=1.0,
        stop_event=threading.Event(),
        snapshot_fn=lambda: HeartbeatSnapshot(state="capturing", detail=None, extras={}),
        led=led,
    )

    states_written = ["booting", "waiting-for-hardware", "capturing"]
    for state in states_written:
        publisher.publish_now(HeartbeatSnapshot(state=state, detail=None, extras={}))

    assert led.states == states_written


def test_indicator_that_raises_does_not_prevent_status_file_write(tmp_path):
    path = tmp_path / "status.json"
    led = _RaisingLed()
    publisher = HeartbeatPublisher(
        path=path,
        interval_s=1.0,
        stop_event=threading.Event(),
        snapshot_fn=lambda: HeartbeatSnapshot(state="capturing", detail=None, extras={}),
        led=led,
    )

    # Must not raise, and the status file must still be written.
    publisher.publish_now(HeartbeatSnapshot(state="capturing", detail=None, extras={}))

    reading = read_heartbeat(path, stale_after_s=5.0)
    assert reading.payload["state"] == "capturing"


def test_indicator_error_is_logged_once_then_suppressed_on_repeat(tmp_path, caplog):
    path = tmp_path / "status.json"
    led = _RaisingLed()
    publisher = HeartbeatPublisher(
        path=path,
        interval_s=1.0,
        stop_event=threading.Event(),
        snapshot_fn=lambda: HeartbeatSnapshot(state="capturing", detail=None, extras={}),
        led=led,
    )

    with caplog.at_level("WARNING", logger="telemetry.ops.heartbeat"):
        for _ in range(3):
            publisher.publish_now(
                HeartbeatSnapshot(state="capturing", detail=None, extras={})
            )

    led_warnings = [r for r in caplog.records if "led" in r.getMessage().lower()]
    assert len(led_warnings) == 1


def test_join_calls_led_close_exactly_once(tmp_path):
    path = tmp_path / "status.json"
    led = _RecordingLed()
    stop_event = threading.Event()
    stop_event.set()  # thread's first wait() call returns True immediately
    publisher = HeartbeatPublisher(
        path=path,
        interval_s=1.0,
        stop_event=stop_event,
        snapshot_fn=lambda: HeartbeatSnapshot(state="capturing", detail=None, extras={}),
        led=led,
    )

    publisher.start()
    publisher.join(timeout=5.0)
    publisher.join(timeout=5.0)  # calling again must not double-close

    assert led.close_count == 1
