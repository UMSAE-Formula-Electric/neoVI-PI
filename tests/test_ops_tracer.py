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


def test_running_logger_reports_capturing_via_a_separate_status_process(tmp_path):
    archive_root = tmp_path / "sessions"
    heartbeat_path = tmp_path / "status.json"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "telemetry.logger.cli",
            "--source",
            "synthetic",
            # Deliberately far beyond this test's own poll budget -- this
            # test asserts the live path only, so the child is killed by
            # the finally block below, not by its own watchdog.
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
        assert "capturing" in human_result.stdout
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
