"""
Requirements covered: GND-02 (dashboard-serving startup path), regression coverage for
02-REVIEW.md's WR-04.

In-process, no subprocess: `telemetry.ground.cli.main()` is called directly with a monkeypatched
`DashboardServer` and a recording `Link` double, following `tests/test_ground_simulate.py`'s own
stated convention of a minimal test double for an external transport (not project logic).
"""

import pytest

from telemetry.ground import cli as ground_cli


class _RecordingLink:
    """A minimal `Link` protocol test double (not project logic): tracks whether `close()` was
    called, exactly like `tests/test_ground_simulate.py::_RecordingLink` tracks sent payloads."""

    def __init__(self) -> None:
        self.closed = False

    def send(self, data: bytes) -> None:
        pass

    def recv(self, timeout=None):
        return None

    def close(self) -> None:
        self.closed = True


class _FailingDashboardServer:
    """Stands in for `telemetry.ground.server.DashboardServer` to reproduce the one real failure
    mode its constructor can raise in production: `ThreadingHTTPServer.__init__`'s `bind()` call
    raising a plain `OSError` (e.g. `[Errno 98] Address already in use`) when re-run against a
    port a previous invocation still holds."""

    def __init__(self, **kwargs) -> None:
        raise OSError(98, "Address already in use")


def test_dashboard_server_bind_failure_exits_via_system_exit_and_closes_the_link(monkeypatch):
    """Regression for WR-04: `DashboardServer(...)` construction in `main()` must be guarded
    exactly like every other startup failure mode in the same function (config load, DBC load,
    gate config load, message index build) -- a bind failure exits via the consistent, logged
    `SystemExit(1)` path, with the already-built `link` closed, rather than an unhandled
    `OSError` traceback that leaks it.

    Confirmed to fail against the pre-fix code (an uncaught `OSError` propagates instead of
    `SystemExit`, and `link.close()` is never reached) before being confirmed to pass against
    the fix."""
    recording_link = _RecordingLink()
    monkeypatch.setattr(ground_cli, "DashboardServer", _FailingDashboardServer)
    monkeypatch.setattr(ground_cli, "_build_link", lambda link_config: recording_link)

    with pytest.raises(SystemExit) as exc_info:
        ground_cli.main(argv=["--serve"])

    assert exc_info.value.code == 1
    assert recording_link.closed, (
        "expected the already-built link to be closed on a dashboard-server bind failure"
    )
