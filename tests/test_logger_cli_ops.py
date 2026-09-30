"""
Task 2's behaviour-first pass for 03-02 (OPS-03): pins the startup disk gate
(refuse at critical, proceed at warn/ok, always log the free-space line)
and the mid-run recheck (degraded, never stopped, rate-limited loud log)
wired into `telemetry.logger.cli`.

Drives `main()` and `_run_session()` directly, in-process, against
`--source synthetic` -- no subprocess, mirroring `tests/test_ops_tracer.py`'s
real-thread-plus-polling style for the mid-run assertions (a clean finish
removes the heartbeat file, so the only way to observe a mid-run `degraded`
snapshot is to poll the file while the session is still running). Every
`check_disk_space_fn` here is an injected fake -- no test touches the real
filesystem's free space.
"""

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from telemetry.capture.hardware_source import HardwareSourceCounters
from telemetry.logger.cli import _parse_args, _run_session, main
from telemetry.ops.disk_monitor import DISK_CRITICAL, DISK_OK, DISK_WARN, DiskReading
from telemetry.ops.hardware_wait import wait_for_hardware
from telemetry.ops.heartbeat import (
    STATE_CAPTURING,
    STATE_DEGRADED,
    STATE_STOPPED_ERROR,
    STATE_WAITING_FOR_HARDWARE,
    HeartbeatPublisher,
    HeartbeatReadError,
    HeartbeatSnapshot,
    read_heartbeat,
)
from telemetry.wire.dictionary import build_id_dictionary

REPO_ROOT = Path(__file__).resolve().parent.parent

_POLL_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.01


def _constant_disk_check(state, *, free_bytes=1_234_567, total_bytes=999_999_999_999):
    """A `check_disk_space_fn` fake that always reports the same band,
    regardless of the archive root or configured thresholds -- the CLI-level
    tests below only care about how `telemetry.logger.cli` reacts to a
    band, not `check_disk_space`'s own boundary logic (pinned separately in
    `tests/test_ops_disk_monitor.py`)."""

    def _fn(path, *, warn_free_bytes, critical_free_bytes):
        return DiskReading(
            measured_path=Path(path),
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            state=state,
        )

    return _fn


def _counting_now_fn(step: float):
    """A deterministic fake clock: each call returns a value exactly `step`
    higher than the previous call, regardless of how much real wall-clock
    time actually elapsed between calls. `_run_session`'s `_capturing_
    snapshot` closure is invoked by exactly one thread (the heartbeat
    publisher's own periodic thread) once its periodic loop starts, plus
    once synchronously by the calling thread before that loop starts -- so
    this counter is never touched concurrently and needs no lock."""
    state = {"value": 0.0}

    def _fn() -> float:
        value = state["value"]
        state["value"] += step
        return value

    return _fn


def _read_heartbeat_state(heartbeat_path: Path):
    """Best-effort read: returns the payload's `state` (and `detail`), or
    `None` if the file does not exist yet or is transiently unreadable
    (the writer's temp-file-then-replace window)."""
    try:
        reading = read_heartbeat(heartbeat_path, stale_after_s=1_000_000.0)
    except HeartbeatReadError:
        return None
    return reading.payload.get("state"), reading.payload.get("detail")


def _poll_until_state(heartbeat_path: Path, target_state: str, timeout_s: float = _POLL_TIMEOUT_S):
    """Poll `heartbeat_path` until its `state` equals `target_state`,
    returning the matching `(state, detail)` pair, or `None` on timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = _read_heartbeat_state(heartbeat_path)
        if result is not None and result[0] == target_state:
            return result
        time.sleep(_POLL_INTERVAL_S)
    return None


def _write_config_with_short_heartbeat(tmp_path: Path, *, heartbeat_interval_s: float) -> Path:
    """Writes a copy of the shipped `config/logger.json` with a shortened
    `ops.heartbeat_interval_s` -- needed so a `main()`-level test (which,
    unlike the `_run_session()`-level tests above, has no way to inject a
    `LoggerConfig` object directly) can observe a mid-run heartbeat tick
    without waiting out the shipped 1.0s default. Mirrors
    `tests/test_logger_cli_smoke.py`'s established technique of writing a
    modified copy of the real config rather than hand-authoring a minimal
    one from scratch."""
    config_data = json.loads((REPO_ROOT / "config" / "logger.json").read_text())
    config_data["ops"]["heartbeat_interval_s"] = heartbeat_interval_s
    config_data["ops"]["heartbeat_stale_after_s"] = heartbeat_interval_s * 100
    config_path = tmp_path / "short_heartbeat_logger.json"
    config_path.write_text(json.dumps(config_data))
    return config_path


class _FakeHardwareFrameSource:
    """A stand-in for `telemetry.capture.hardware_source.HardwareFrameSource`
    that never touches the real `ics` module -- monkeypatched in for
    `--source hardware` tests below so a run can proceed past a successful
    `wait_for_hardware` without a real neoVI device or a hand-rolled
    ics-shaped fake SDK. Yields no frames; blocks on the same
    `stop_event.wait(timeout=poll_interval_s)` idiom the real class uses,
    so it is stop-responsive exactly like the real thing."""

    def __init__(self, *, channels, poll_interval_s, hardware_serial, stop_event, sdk=None):
        self.counters = HardwareSourceCounters()
        self._stop_event = stop_event
        self._poll_interval_s = poll_interval_s

    def captured_frames(self):
        while not self._stop_event.wait(timeout=self._poll_interval_s):
            self.counters.poll_count += 1
        return
        yield  # pragma: no cover -- unreachable; makes this a generator function


class _ControllableWait:
    """A `wait_for_hardware_fn` double that calls `on_waiting` once
    (writing a `waiting-for-hardware` snapshot the test can observe), then
    blocks on `self.release` until the test tells it to proceed -- lets a
    test deterministically observe "still waiting" before letting the run
    continue, with no reliance on real timing/backoff."""

    def __init__(self, *, return_value: bool = True):
        self.on_waiting_seen = threading.Event()
        self.release = threading.Event()
        self._return_value = return_value
        self.calls = []
        self.received_stop_event = None

    def __call__(self, *, stop_event, on_waiting):
        self.received_stop_event = stop_event
        on_waiting(1, 0.01)
        self.calls.append((1, 0.01))
        self.on_waiting_seen.set()
        self.release.wait(timeout=5.0)
        return self._return_value


# ---------------------------------------------------------------------------
# main(): startup gate -- critical refuses, warn/ok proceed, every band logs.
# ---------------------------------------------------------------------------


def test_critical_band_at_startup_exits_1_creates_no_session_and_publishes_stopped_error(
    tmp_path, logger_config
):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"
    free_bytes = 42

    argv = [
        "--source",
        "synthetic",
        "--duration-s",
        "0.3",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    with pytest.raises(SystemExit) as exc_info:
        main(argv, check_disk_space_fn=_constant_disk_check(DISK_CRITICAL, free_bytes=free_bytes))

    assert exc_info.value.code == 1
    assert not archive_root.exists()

    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["state"] == STATE_STOPPED_ERROR
    assert str(free_bytes) in payload["detail"]
    assert str(logger_config.ops.disk_critical_free_bytes) in payload["detail"]
    assert payload["extras"]["disk_state"] == DISK_CRITICAL
    assert payload["extras"]["disk_free_bytes"] == free_bytes


def test_warn_band_at_startup_proceeds_to_a_completed_session(tmp_path):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    argv = [
        "--source",
        "synthetic",
        "--duration-s",
        "0.3",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    # Must not raise -- a warn-band start is not a refusal.
    main(argv, check_disk_space_fn=_constant_disk_check(DISK_WARN))

    session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    assert (session_dirs[0] / ".done").exists()


@pytest.mark.parametrize("band", [DISK_OK, DISK_WARN, DISK_CRITICAL])
def test_every_start_logs_the_free_space_line_in_every_band(tmp_path, caplog, band):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"
    free_bytes = 7_777_777

    argv = [
        "--source",
        "synthetic",
        "--duration-s",
        "0.3",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    with caplog.at_level("INFO", logger="telemetry.logger.cli"):
        if band == DISK_CRITICAL:
            with pytest.raises(SystemExit):
                main(argv, check_disk_space_fn=_constant_disk_check(band, free_bytes=free_bytes))
        else:
            main(argv, check_disk_space_fn=_constant_disk_check(band, free_bytes=free_bytes))

    startup_lines = [
        r.message
        for r in caplog.records
        if r.name == "telemetry.logger.cli" and "disk space at startup" in r.message
    ]
    assert len(startup_lines) == 1
    assert str(free_bytes) in startup_lines[0]
    assert band in startup_lines[0]


# ---------------------------------------------------------------------------
# _run_session(): mid-run recheck -- degraded (never stopped-error), a run
# in progress is never halted, and the archive still reaches a clean finish.
# ---------------------------------------------------------------------------


def _build_run_session_args(dbc, logger_config, tmp_path, *, heartbeat_interval_s, duration_s):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"
    config = replace(
        logger_config,
        archive=replace(logger_config.archive, root_dir=archive_root),
        ops=replace(
            logger_config.ops,
            heartbeat_path=heartbeat_path,
            heartbeat_interval_s=heartbeat_interval_s,
            heartbeat_stale_after_s=heartbeat_interval_s * 10,
        ),
    )
    dictionary = build_id_dictionary(dbc, dbc_path=config.dbc_path)
    from telemetry.logger.config import resolve_allowlist

    allowlist = resolve_allowlist(config, dbc)
    args = _parse_args(
        ["--source", "synthetic", "--duration-s", str(duration_s), "--bracket", "typical"]
    )
    return config, args, dictionary, allowlist, heartbeat_path


def _start_run_session_in_background(
    config, args, dbc, dictionary, allowlist, stop_event, publisher, **kwargs
):
    result = {}

    def _run():
        result["exit_code"] = _run_session(
            config, args, dbc, dictionary, allowlist, stop_event, publisher, **kwargs
        )

    thread = threading.Thread(target=_run, name="test-run-session")
    thread.start()
    return thread, result


@pytest.mark.parametrize("band", [DISK_WARN, DISK_CRITICAL])
def test_mid_run_non_ok_band_reports_degraded_never_stops_and_finishes_cleanly(
    dbc, logger_config, tmp_path, band
):
    config, args, dictionary, allowlist, heartbeat_path = _build_run_session_args(
        dbc, logger_config, tmp_path, heartbeat_interval_s=0.02, duration_s=1.0
    )
    stop_event = threading.Event()
    publisher = HeartbeatPublisher(
        path=config.ops.heartbeat_path,
        interval_s=config.ops.heartbeat_interval_s,
        stop_event=stop_event,
        snapshot_fn=lambda: HeartbeatSnapshot(state="booting", detail=None, extras={}),
    )
    publisher.publish_now(publisher.snapshot_fn())

    thread, result = _start_run_session_in_background(
        config,
        args,
        dbc,
        dictionary,
        allowlist,
        stop_event,
        publisher,
        check_disk_space_fn=_constant_disk_check(band),
    )

    found = _poll_until_state(heartbeat_path, STATE_DEGRADED)
    thread.join(timeout=10.0)
    assert not thread.is_alive(), "run_session did not finish in time"

    assert found is not None, "never observed a degraded heartbeat during the run"
    observed_state, observed_detail = found
    assert observed_state == STATE_DEGRADED
    assert band in observed_detail
    # A run already in progress is NEVER stopped by this check, regardless
    # of band, and the archive still reaches a clean finish.
    assert result["exit_code"] == 0
    session_dirs = [p for p in config.archive.root_dir.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    assert (session_dirs[0] / ".done").exists()
    # A clean finish removes the heartbeat file -- its absence, not a
    # stopped-error state, is the terminal signal.
    assert not heartbeat_path.exists()


def _run_for_a_controlled_real_window(
    config, args, dbc, dictionary, allowlist, stop_event, publisher, real_window_s, **kwargs
):
    """Runs `_run_session` in a background thread for approximately
    `real_window_s` of REAL wall-clock time, then sets `stop_event` itself
    and joins. `args.duration_s` (30s of synthetic frames -- `SyntheticFrame
    Source` has no per-frame real-time throttle, see `telemetry.synth.
    generator`) is deliberately generous so the synthetic source never
    exhausts and ends the run on its own before this function's own
    stop_event.set() does -- that is what makes the number of real
    heartbeat ticks within `real_window_s` controllable by wall-clock time
    alone, independent of frame count."""
    thread, result = _start_run_session_in_background(
        config, args, dbc, dictionary, allowlist, stop_event, publisher, **kwargs
    )
    time.sleep(real_window_s)
    stop_event.set()
    thread.join(timeout=10.0)
    assert not thread.is_alive(), "run_session did not finish in time"
    return result


def test_mid_run_disk_log_does_not_repeat_within_the_rate_limit_interval(
    dbc, logger_config, tmp_path, caplog
):
    config, args, dictionary, allowlist, heartbeat_path = _build_run_session_args(
        dbc, logger_config, tmp_path, heartbeat_interval_s=0.02, duration_s=30.0
    )
    stop_event = threading.Event()
    publisher = HeartbeatPublisher(
        path=config.ops.heartbeat_path,
        interval_s=config.ops.heartbeat_interval_s,
        stop_event=stop_event,
        snapshot_fn=lambda: HeartbeatSnapshot(state="booting", detail=None, extras={}),
    )
    publisher.publish_now(publisher.snapshot_fn())

    # Each tick's simulated clock advances by only 0.5s -- across the many
    # real ticks that occur over this controlled real window, the
    # simulated elapsed time never approaches the 60s rate-limit interval,
    # so only the initial transition-into-warn log should ever fire.
    with caplog.at_level("WARNING", logger="telemetry.logger.cli"):
        result = _run_for_a_controlled_real_window(
            config,
            args,
            dbc,
            dictionary,
            allowlist,
            stop_event,
            publisher,
            real_window_s=0.3,
            check_disk_space_fn=_constant_disk_check(DISK_WARN),
            now_fn=_counting_now_fn(step=0.5),
        )

    assert result["exit_code"] == 0
    warn_logs = [
        r
        for r in caplog.records
        if r.name == "telemetry.logger.cli" and "disk space warn during session" in r.message
    ]
    assert len(warn_logs) == 1


def test_mid_run_disk_log_repeats_once_the_rate_limit_interval_elapses(
    dbc, logger_config, tmp_path, caplog
):
    config, args, dictionary, allowlist, heartbeat_path = _build_run_session_args(
        dbc, logger_config, tmp_path, heartbeat_interval_s=0.02, duration_s=30.0
    )
    stop_event = threading.Event()
    publisher = HeartbeatPublisher(
        path=config.ops.heartbeat_path,
        interval_s=config.ops.heartbeat_interval_s,
        stop_event=stop_event,
        snapshot_fn=lambda: HeartbeatSnapshot(state="booting", detail=None, extras={}),
    )
    publisher.publish_now(publisher.snapshot_fn())

    # Each tick's simulated clock advances by 100s -- every tick after the
    # first sees the rate-limit interval already elapsed, so the loud log
    # must fire again and again while the band persists.
    with caplog.at_level("WARNING", logger="telemetry.logger.cli"):
        result = _run_for_a_controlled_real_window(
            config,
            args,
            dbc,
            dictionary,
            allowlist,
            stop_event,
            publisher,
            real_window_s=0.3,
            check_disk_space_fn=_constant_disk_check(DISK_WARN),
            now_fn=_counting_now_fn(step=100.0),
        )

    assert result["exit_code"] == 0
    warn_logs = [
        r
        for r in caplog.records
        if r.name == "telemetry.logger.cli" and "disk space warn during session" in r.message
    ]
    assert len(warn_logs) > 1


# ---------------------------------------------------------------------------
# 03-04 (OPS-01): the boot race -- main() waits, recovers, or stops cleanly.
# ---------------------------------------------------------------------------


def test_hardware_boot_race_waits_then_recovers_to_capturing(tmp_path, monkeypatch):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"
    config_path = _write_config_with_short_heartbeat(tmp_path, heartbeat_interval_s=0.02)
    monkeypatch.setattr("telemetry.logger.cli.HardwareFrameSource", _FakeHardwareFrameSource)
    # main() runs on a background thread here (needed to observe the
    # mid-wait state before letting it proceed) -- signal.signal() only
    # works on the main interpreter thread, so the real
    # _install_signal_handlers call must be skipped for this test only.
    # Signal-handler installation itself is exercised elsewhere; this test
    # is about the heartbeat/hardware-wait state machine.
    monkeypatch.setattr("telemetry.logger.cli._install_signal_handlers", lambda stop_event: None)

    controllable = _ControllableWait(return_value=True)
    argv = [
        "--config",
        str(config_path),
        "--source",
        "hardware",
        "--duration-s",
        "0.5",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    thread = threading.Thread(
        target=lambda: main(
            argv,
            check_disk_space_fn=_constant_disk_check(DISK_OK),
            wait_for_hardware_fn=controllable,
        ),
        name="test-main-hardware-wait",
    )
    thread.start()

    assert controllable.on_waiting_seen.wait(timeout=5.0), "on_waiting was never called"
    observed = _read_heartbeat_state(heartbeat_path)
    assert observed is not None
    assert observed[0] == STATE_WAITING_FOR_HARDWARE
    # No session directory exists while still waiting for hardware.
    assert not archive_root.exists()

    controllable.release.set()  # let wait_for_hardware_fn return True -- device "found"

    found = _poll_until_state(heartbeat_path, STATE_CAPTURING)
    assert found is not None, "never observed a capturing heartbeat once the wait resolved"

    thread.join(timeout=10.0)
    assert not thread.is_alive(), "main() did not finish in time"

    session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    assert (session_dirs[0] / ".done").exists()
    # A clean finish removes the heartbeat file -- its absence is the
    # terminal signal.
    assert not heartbeat_path.exists()


def test_hardware_boot_race_stop_event_exits_zero_and_removes_status_file(tmp_path):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    def _fake_wait_then_stop(*, stop_event, on_waiting):
        on_waiting(1, 0.01)
        stop_event.set()  # the operator stops the logger while it waits
        return False

    argv = [
        "--source",
        "hardware",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    # main() must return normally -- an operator stopping a logger that
    # never saw hardware is a clean stop (implicit exit code 0), not an
    # error; must NOT raise SystemExit.
    main(
        argv,
        check_disk_space_fn=_constant_disk_check(DISK_OK),
        wait_for_hardware_fn=_fake_wait_then_stop,
    )

    assert not archive_root.exists()
    assert not heartbeat_path.exists()


def test_synthetic_source_never_calls_wait_for_hardware(tmp_path):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    def _fail_if_called(*, stop_event, on_waiting):
        raise AssertionError(
            "wait_for_hardware_fn must not be called for --source synthetic"
        )

    argv = [
        "--source",
        "synthetic",
        "--duration-s",
        "0.3",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    main(
        argv,
        check_disk_space_fn=_constant_disk_check(DISK_OK),
        wait_for_hardware_fn=_fail_if_called,
    )

    session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    assert (session_dirs[0] / ".done").exists()


# ---------------------------------------------------------------------------
# 03-04 (OPS-01): terminal state -- clean finish removes the file, every
# bad ending leaves one naming the failing condition(s).
# ---------------------------------------------------------------------------


def test_clean_finish_leaves_no_status_file(tmp_path):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    argv = [
        "--source",
        "synthetic",
        "--duration-s",
        "0.3",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    main(argv, check_disk_space_fn=_constant_disk_check(DISK_OK))  # must not raise

    session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    assert (session_dirs[0] / ".done").exists()
    assert not heartbeat_path.exists()


def _write_config_for_archive_overflow(tmp_path: Path) -> Path:
    """Config that reliably overflows the archive queue on the second
    frame submitted -- mirrors `tests/test_logger_cli_smoke.py::
    test_cli_archive_overflow_leaves_no_done_marker_and_exits_nonzero`'s
    already-established, non-racy technique: `queue_depth=1` plus an
    fsync on every record makes the archive consumer thread reliably
    slower than the synthetic capture loop producing frames."""
    config_data = json.loads((REPO_ROOT / "config" / "logger.json").read_text())
    config_data["archive"]["queue_depth"] = 1
    config_data["archive"]["flush_every_records"] = 1
    config_data["ops"]["heartbeat_interval_s"] = 0.02
    config_data["ops"]["heartbeat_stale_after_s"] = 2.0
    config_path = tmp_path / "overflow_logger.json"
    config_path.write_text(json.dumps(config_data))
    return config_path


def test_archive_overflow_leaves_stopped_error_status_file_naming_condition(tmp_path):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"
    config_path = _write_config_for_archive_overflow(tmp_path)

    argv = [
        "--config",
        str(config_path),
        "--source",
        "synthetic",
        "--duration-s",
        "1.0",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    with pytest.raises(SystemExit) as exc_info:
        main(argv, check_disk_space_fn=_constant_disk_check(DISK_OK))
    assert exc_info.value.code == 1

    session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    assert not (session_dirs[0] / ".done").exists()

    # The file is left in place -- NOT removed -- naming the condition.
    assert heartbeat_path.exists()
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["state"] == STATE_STOPPED_ERROR
    assert "archive_overflow" in payload["detail"]
    assert payload["extras"]["archive_overflow"] is True


def test_capture_loop_exception_leaves_stopped_error_even_if_writer_closed_cleanly(
    tmp_path, monkeypatch
):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    class _RaisingSyntheticFrameSource:
        def __init__(self, **kwargs):
            pass

        def frames(self):
            raise RuntimeError("synthetic source exploded")
            yield  # pragma: no cover -- unreachable; makes this a generator function

    monkeypatch.setattr(
        "telemetry.logger.cli.SyntheticFrameSource", _RaisingSyntheticFrameSource
    )

    argv = [
        "--source",
        "synthetic",
        "--duration-s",
        "1.0",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    # The archive writer itself closes without error (zero frames were
    # ever submitted, so archive_closed_cleanly is True and the exit code
    # is 0) -- but the heartbeat must still report stopped-error because
    # the capture loop raised.
    main(argv, check_disk_space_fn=_constant_disk_check(DISK_OK))

    session_dirs = [p for p in archive_root.iterdir() if p.is_dir()]
    assert len(session_dirs) == 1
    assert (session_dirs[0] / ".done").exists()

    assert heartbeat_path.exists()
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["state"] == STATE_STOPPED_ERROR
    assert "capture_loop_exception" in payload["detail"]
    assert payload["extras"]["capture_loop_exception"] is True
    assert payload["extras"]["archive_closed_cleanly"] is True


# ---------------------------------------------------------------------------
# WR-01 (03-REVIEW.md): a construction failure -- `new_session()` raising
# because the archive filesystem isn't mounted/writable, or a
# `wait_for_hardware_fn` exception the SDK does not own -- must still
# publish a terminal stopped-error heartbeat naming the condition before
# the exception propagates, exactly like the existing capture-loop handler.
# ---------------------------------------------------------------------------


def test_session_construction_failure_publishes_stopped_error_before_propagating(
    tmp_path, monkeypatch
):
    """`new_session()` raising (e.g. the archive filesystem isn't mounted
    or writable yet) happens BEFORE `_run_session`'s capture-loop `try`
    block -- prior to the WR-01 fix this propagated straight out of
    `_run_session` and `main()` uncaught, leaving the heartbeat file at
    whatever it last held (`booting`) with no explanatory stopped-error
    write at all."""
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    def _raise_new_session(root_dir, *, config_hash):
        raise PermissionError("simulated: archive root not writable")

    monkeypatch.setattr("telemetry.logger.cli.new_session", _raise_new_session)

    argv = [
        "--source",
        "synthetic",
        "--duration-s",
        "0.3",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    # The construction failure is still an unhandled exception once the
    # heartbeat has been published -- it is not swallowed or converted
    # into a SystemExit, it propagates, exactly as an exception the
    # capture-loop's own `except Exception:` cannot name would.
    with pytest.raises(PermissionError, match="simulated: archive root not writable"):
        main(argv, check_disk_space_fn=_constant_disk_check(DISK_OK))

    assert heartbeat_path.exists(), (
        "a construction failure must leave a stopped-error heartbeat "
        "behind, not the stale booting snapshot main() published at startup"
    )
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["state"] == STATE_STOPPED_ERROR
    assert "simulated: archive root not writable" in payload["detail"]


def test_wait_for_hardware_unhandled_exception_publishes_stopped_error_before_propagating(
    tmp_path,
):
    """An exception `wait_for_hardware` does not own (not `sdk.RuntimeError`)
    is documented to propagate out of `wait_for_hardware` itself -- but
    prior to the WR-01 fix, `main()` had no `try`/`except` around that
    call either, so it propagated straight out of `main()` with no
    stopped-error heartbeat published first."""
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    def _raise_unowned_exception(*, stop_event, on_waiting):
        raise ValueError("simulated: exception the SDK does not own")

    argv = [
        "--source",
        "hardware",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    with pytest.raises(ValueError, match="simulated: exception the SDK does not own"):
        main(
            argv,
            check_disk_space_fn=_constant_disk_check(DISK_OK),
            wait_for_hardware_fn=_raise_unowned_exception,
        )

    assert not archive_root.exists(), "no session should ever be created on this path"
    assert heartbeat_path.exists(), (
        "a wait_for_hardware failure must leave a stopped-error heartbeat "
        "behind, not the stale booting snapshot main() published at startup"
    )
    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["state"] == STATE_STOPPED_ERROR
    assert "simulated: exception the SDK does not own" in payload["detail"]


# ---------------------------------------------------------------------------
# 03-04: DBC-load / allowlist-resolution failures publish stopped-error
# before SystemExit(1); a config-load failure publishes nothing.
# ---------------------------------------------------------------------------


def test_dbc_load_failure_publishes_stopped_error_before_exit(tmp_path, monkeypatch):
    from telemetry.wire.dictionary import DbcLoadError

    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    def _raise_dbc_load_error(path):
        raise DbcLoadError("simulated DBC load failure")

    monkeypatch.setattr("telemetry.logger.cli.load_dbc", _raise_dbc_load_error)

    argv = [
        "--source",
        "synthetic",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    with pytest.raises(SystemExit) as exc_info:
        main(argv, check_disk_space_fn=_constant_disk_check(DISK_OK))
    assert exc_info.value.code == 1

    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["state"] == STATE_STOPPED_ERROR
    assert "DBC" in payload["detail"]
    assert "simulated DBC load failure" in payload["detail"]


def test_allowlist_resolution_failure_publishes_stopped_error_before_exit(
    tmp_path, monkeypatch
):
    from telemetry.logger.config import LoggerConfigError

    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    def _raise_allowlist_error(config, db):
        raise LoggerConfigError("simulated allowlist resolution failure")

    monkeypatch.setattr("telemetry.logger.cli.resolve_allowlist", _raise_allowlist_error)

    argv = [
        "--source",
        "synthetic",
        "--archive-root",
        str(archive_root),
        "--heartbeat-path",
        str(heartbeat_path),
    ]

    with pytest.raises(SystemExit) as exc_info:
        main(argv, check_disk_space_fn=_constant_disk_check(DISK_OK))
    assert exc_info.value.code == 1

    payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert payload["state"] == STATE_STOPPED_ERROR
    assert "allowlist" in payload["detail"]
    assert "simulated allowlist resolution failure" in payload["detail"]


def test_config_load_failure_publishes_no_status_file(tmp_path, monkeypatch):
    from telemetry.logger.config import LoggerConfigError

    heartbeat_path = tmp_path / "status.json"

    def _raise_config_load_error(path):
        raise LoggerConfigError("simulated config load failure")

    monkeypatch.setattr("telemetry.logger.cli.load_logger_config", _raise_config_load_error)

    argv = ["--source", "synthetic", "--heartbeat-path", str(heartbeat_path)]

    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 1

    # config.ops.heartbeat_path is not known at this point -- no
    # HeartbeatPublisher was ever constructed, so no file exists at all,
    # including at the path this run's own CLI flag would have named.
    assert not heartbeat_path.exists()
