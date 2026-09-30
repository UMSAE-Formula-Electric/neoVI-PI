"""
Task 1's end-to-end proof for 03-01 (OPS-02): a running logger publishes a
status file at 1 Hz, and a second process (`telemetry.ops.cli`,
`telemetry-status`) renders it -- proven as a real two-process run, not
per-layer unit tests. Follows `tests/test_logger_cli_smoke.py`'s real-
subprocess shape (`sys.executable -m ...`, `PYTHONPATH=src` in `env`, `cwd`
at the repo root).

Task 2 (`tests/test_ops_heartbeat.py`, `tests/test_logger_config.py`) pins
the failure modes (atomicity, reboot-boundary staleness, fail-closed
config) as isolated unit tests -- this file only proves the live path.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

_POLL_BUDGET_S = 30.0
_POLL_INTERVAL_S = 0.5


def _env():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    return env


def _run_status_cli(heartbeat_path, *, as_json=False):
    argv = [
        sys.executable,
        "-m",
        "telemetry.ops.cli",
        "--heartbeat-path",
        str(heartbeat_path),
    ]
    if as_json:
        argv.append("--json")
    return subprocess.run(
        argv, cwd=str(REPO_ROOT), env=_env(), capture_output=True, text=True, timeout=30
    )


def _write_config_with_large_queue_depth(tmp_path: Path) -> Path:
    """A copy of the shipped `config/logger.json` with `archive.queue_depth`
    raised far above the default (50000).

    03-04 (OPS-01) added an unconditional terminal-state write on shutdown,
    which surfaced a pre-existing latent race in this test:
    `telemetry.synth.generator.SyntheticFrameSource` has NO per-frame
    real-time throttle (confirmed empirically in 03-02) -- `--duration-s
    120` against the shipped 50000-deep archive queue was measured this
    session to generate its full frame burst and hit `archive_overflow`
    (CAP-03/CAP-04's fatal-by-design overflow) in well under 2 real
    seconds, every time. Before 03-04, a bad ending like this left the
    heartbeat file showing whatever state its last periodic tick had
    written (often a stale `capturing`), which is exactly why this race
    was invisible until now. Raising `queue_depth` to comfortably exceed
    the full burst (measured this session at 447,652 frames for
    `--duration-s 120`) lets the run take several real seconds to archive
    everything and exit cleanly, which is what this test actually needs:
    a real, live, `capturing` subprocess for long enough to observe over
    this file's own poll budget -- not a race against `archive_overflow`.
    """
    config_data = json.loads((REPO_ROOT / "config" / "logger.json").read_text())
    config_data["archive"]["queue_depth"] = 2_000_000
    config_path = tmp_path / "large_queue_logger.json"
    config_path.write_text(json.dumps(config_data))
    return config_path


def test_running_logger_reports_capturing_via_a_separate_status_process(tmp_path):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"
    config_path = _write_config_with_large_queue_depth(tmp_path)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "telemetry.logger.cli",
            "--config",
            str(config_path),
            "--source",
            "synthetic",
            # Deliberately far beyond this test's own poll budget -- this
            # test asserts the live path only, so the child is killed by
            # the finally block below, not by its own watchdog. See
            # _write_config_with_large_queue_depth's docstring for why
            # this now needs a raised queue_depth to avoid archive_overflow
            # given SyntheticFrameSource's confirmed lack of throttling.
            "--duration-s",
            "120",
            "--archive-root",
            str(archive_root),
            "--heartbeat-path",
            str(heartbeat_path),
        ],
        cwd=str(REPO_ROOT),
        env=_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + _POLL_BUDGET_S
        state = None
        last_json_result = None
        while time.monotonic() < deadline:
            last_json_result = _run_status_cli(heartbeat_path, as_json=True)
            if last_json_result.returncode == 0:
                payload = json.loads(last_json_result.stdout)
                state = payload["state"]
                if state == "capturing":
                    break
            time.sleep(_POLL_INTERVAL_S)

        assert state == "capturing", (
            f"heartbeat never reached 'capturing' within {_POLL_BUDGET_S}s "
            f"(last status-cli result: {last_json_result})"
        )
        assert last_json_result.returncode == 0

        human_result = _run_status_cli(heartbeat_path, as_json=False)
        assert human_result.returncode == 0
        # 03-05 corrects the two-outputs split: stdout is reserved solely
        # for the single `--json` line, so the plain-text report -- like
        # every other log line this process emits -- goes to stderr.
        assert human_result.stdout == ""
        assert "capturing" in human_result.stderr
    finally:
        # Popen.terminate() on Windows never reaches a Python signal
        # handler (recorded project fact, tests/test_logger_cli_smoke.py's
        # sibling tests rely on subprocess.run's own bounded --duration-s
        # instead) -- an unclean child exit here is expected and is
        # deliberately not asserted against.
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def test_clean_exit_leaves_no_status_file_and_status_cli_exits_four(tmp_path):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "telemetry.logger.cli",
            "--source",
            "synthetic",
            "--duration-s",
            "5",
            "--archive-root",
            str(archive_root),
            "--heartbeat-path",
            str(heartbeat_path),
        ],
        cwd=str(REPO_ROOT),
        env=_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not heartbeat_path.exists()

    status_result = _run_status_cli(heartbeat_path)
    assert status_result.returncode == 4
