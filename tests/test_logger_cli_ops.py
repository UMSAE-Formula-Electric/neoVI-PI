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

from telemetry.logger.cli import _parse_args, _run_session, main
from telemetry.ops.disk_monitor import DISK_CRITICAL, DISK_OK, DISK_WARN, DiskReading
from telemetry.ops.heartbeat import (
    STATE_DEGRADED,
    STATE_STOPPED_ERROR,
    HeartbeatPublisher,
    HeartbeatReadError,
    HeartbeatSnapshot,
    read_heartbeat,
)
from telemetry.wire.dictionary import build_id_dictionary

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
