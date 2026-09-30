"""
03-05's behaviour-first pass for the operator-facing half of the heartbeat
(OPS-02): pins `telemetry.ops.cli`'s rendering -- one meaning and one next
action per state, staleness leading both the headline and the exit code,
the `capturing`/`degraded` evidence line built from the exact `extras`
keys `telemetry.logger.cli`'s capturing closure writes, and the corrected
two-outputs discipline (stdout carries only the single `--json` line; every
human-readable line, including the plain-text report, goes to stderr).

Every fixture status file is built with the real `write_heartbeat`, and
every staleness comparison is driven by an injected `now_fn` passed
straight through `telemetry.ops.cli.main`'s own `now_fn` seam -- never a
`time.sleep`. `tests/test_ops_tracer.py` still owns the real two-process,
real-clock proof; this file is the isolated, deterministic pin for every
rendering path that proof cannot practically exercise for all five states
and every staleness reason.
"""

import json

import pytest

from telemetry.ops.cli import EXIT_ERROR, EXIT_FRESH_BAD, EXIT_FRESH_OK, EXIT_NOT_RUNNING, EXIT_STALE, main
from telemetry.ops.heartbeat import (
    HEARTBEAT_STATES,
    STATE_BOOTING,
    STATE_CAPTURING,
    STATE_DEGRADED,
    STATE_STOPPED_ERROR,
    STATE_WAITING_FOR_HARDWARE,
    HeartbeatSnapshot,
    write_heartbeat,
)

_WRITTEN_AT = 1_000.0
_FRESH_NOW = 1_000.5  # age_s = 0.5, well under any stale_after_s used below.
_DEFAULT_STALE_AFTER_S = 100.0

_CAPTURING_EXTRAS = {
    "session_name": "20260930_120000",
    "frames_per_s": 3821.4,
    "frames_submitted": 100_000,
    "records_written": 99_950,
}


def _write_status(path, *, state, detail=None, extras=None, written_at=_WRITTEN_AT):
    write_heartbeat(
        path,
        HeartbeatSnapshot(state=state, detail=detail, extras=extras or {}),
        now_fn=lambda: written_at,
    )


def _call_status_cli(
    heartbeat_path,
    *,
    as_json=False,
    now_fn=lambda: _FRESH_NOW,
    stale_after_s=_DEFAULT_STALE_AFTER_S,
):
    argv = [
        "--heartbeat-path",
        str(heartbeat_path),
        "--stale-after-s",
        str(stale_after_s),
    ]
    if as_json:
        argv.append("--json")
    with pytest.raises(SystemExit) as exc_info:
        main(argv, now_fn=now_fn)
    return exc_info.value.code


# ---------------------------------------------------------------------------
# Every state renders a meaning and a next action, parameterised over the
# imported HEARTBEAT_STATES tuple.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", HEARTBEAT_STATES)
def test_every_heartbeat_state_renders_a_meaning_and_next_action(tmp_path, state, capsys):
    path = tmp_path / "status.json"
    extras = dict(_CAPTURING_EXTRAS) if state in (STATE_CAPTURING, STATE_DEGRADED) else {}
    detail = "some concrete detail" if state in (STATE_DEGRADED, STATE_STOPPED_ERROR) else None
    _write_status(path, state=state, detail=detail, extras=extras)

    code = _call_status_cli(path)

    captured = capsys.readouterr()
    assert captured.out == "", "human mode must leave stdout empty (03-05 corrects the stream split)"
    assert state in captured.err
    lines = captured.err.splitlines()
    assert any(line.startswith("state:") for line in lines)
    # A meaning line and a next-action line must both be present and must
    # be genuinely distinct text, not the same line repeated.
    assert len(lines) >= 3
    meaning_line = lines[1]
    next_line = next(line for line in lines if line.startswith("next:"))
    assert meaning_line != next_line
    assert meaning_line.strip() != ""
    assert next_line.strip() != "next:"

    if state in ("booting", "waiting-for-hardware", "capturing"):
        assert code == EXIT_FRESH_OK
    else:
        assert code == EXIT_FRESH_BAD


def test_all_five_states_have_pairwise_distinct_meaning_and_next_action_lines(tmp_path, capsys):
    meanings = {}
    next_actions = {}
    for state in HEARTBEAT_STATES:
        path = tmp_path / f"status_{state}.json"
        extras = dict(_CAPTURING_EXTRAS) if state in (STATE_CAPTURING, STATE_DEGRADED) else {}
        _write_status(path, state=state, extras=extras)
        _call_status_cli(path)
        err = capsys.readouterr().err
        lines = err.splitlines()
        meanings[state] = lines[1]
        next_actions[state] = next(line for line in lines if line.startswith("next:"))

    assert len(set(meanings.values())) == len(HEARTBEAT_STATES)
    assert len(set(next_actions.values())) == len(HEARTBEAT_STATES)


# ---------------------------------------------------------------------------
# The evidence line behind `capturing` (and `degraded`).
# ---------------------------------------------------------------------------


def test_fresh_capturing_renders_evidence_line_with_session_rate_and_frame_counts(tmp_path, capsys):
    path = tmp_path / "status.json"
    _write_status(path, state=STATE_CAPTURING, extras=_CAPTURING_EXTRAS)

    code = _call_status_cli(path)

    err = capsys.readouterr().err
    assert code == EXIT_FRESH_OK
    assert _CAPTURING_EXTRAS["session_name"] in err
    assert "3821.4" in err
    assert "100000" in err
    assert "99950" in err


def test_fresh_capturing_with_zero_frames_per_s_still_capturing_and_exits_zero(tmp_path, capsys):
    path = tmp_path / "status.json"
    extras = dict(_CAPTURING_EXTRAS)
    extras["frames_per_s"] = 0.0
    _write_status(path, state=STATE_CAPTURING, extras=extras)

    code = _call_status_cli(path)

    err = capsys.readouterr().err
    assert code == EXIT_FRESH_OK
    assert STATE_CAPTURING in err
    assert "degraded" not in err.lower()


def test_fresh_degraded_names_the_detail_the_publisher_recorded(tmp_path, capsys):
    path = tmp_path / "status.json"
    _write_status(
        path,
        state=STATE_DEGRADED,
        detail="disk critical: free_bytes=1000",
        extras=_CAPTURING_EXTRAS,
    )

    code = _call_status_cli(path)

    err = capsys.readouterr().err
    assert code == EXIT_FRESH_BAD
    assert "disk critical: free_bytes=1000" in err


# ---------------------------------------------------------------------------
# Staleness outranks state, in both the headline and the exit code.
# ---------------------------------------------------------------------------


def test_stale_capturing_leads_with_staleness_includes_age_and_exits_three(tmp_path, capsys):
    path = tmp_path / "status.json"
    _write_status(path, state=STATE_CAPTURING, extras=_CAPTURING_EXTRAS, written_at=1_000.0)

    code = _call_status_cli(path, now_fn=lambda: 1_010.0, stale_after_s=5.0)

    err = capsys.readouterr().err
    assert code == EXIT_STALE
    lines = err.splitlines()
    assert lines[0].startswith("STALE")
    assert "10.0" in lines[0] or "10.000" in lines[0]
    assert STATE_CAPTURING in lines[0]


def test_stale_degraded_exits_three_not_two(tmp_path, capsys):
    path = tmp_path / "status.json"
    _write_status(
        path,
        state=STATE_DEGRADED,
        detail="disk warn: free_bytes=999",
        extras=_CAPTURING_EXTRAS,
        written_at=1_000.0,
    )

    code = _call_status_cli(path, now_fn=lambda: 1_010.0, stale_after_s=5.0)

    err = capsys.readouterr().err
    assert code == EXIT_STALE
    assert err.splitlines()[0].startswith("STALE")


def test_clock_went_backwards_renders_actionable_reboot_message_and_exits_three(tmp_path, capsys):
    path = tmp_path / "status.json"
    # written_at is AHEAD of the reader's clock -- the reboot-boundary case.
    _write_status(path, state=STATE_CAPTURING, extras=_CAPTURING_EXTRAS, written_at=2_000.0)

    code = _call_status_cli(path, now_fn=lambda: 1_000.0, stale_after_s=5.0)

    err = capsys.readouterr().err
    assert code == EXIT_STALE
    assert "clock-went-backwards" in err
    assert "reboot" in err.lower()
    assert "cannot be trusted" in err.lower() or "not trustworthy" in err.lower() or "not be trusted" in err.lower()


# ---------------------------------------------------------------------------
# booting / waiting-for-hardware are not errors.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", [STATE_BOOTING, STATE_WAITING_FOR_HARDWARE])
def test_booting_and_waiting_for_hardware_exit_zero(tmp_path, capsys, state):
    path = tmp_path / "status.json"
    _write_status(path, state=state)

    code = _call_status_cli(path)

    assert code == EXIT_FRESH_OK


# ---------------------------------------------------------------------------
# Absent, malformed, and missing-key files.
# ---------------------------------------------------------------------------


def test_absent_status_file_exits_four_names_path_and_points_at_journal(tmp_path, caplog, capsys):
    path = tmp_path / "does_not_exist.json"

    with caplog.at_level("ERROR", logger="telemetry.ops.cli"):
        code = _call_status_cli(path)

    assert code == EXIT_NOT_RUNNING
    assert str(path) in caplog.text
    assert "not running" in caplog.text.lower()
    assert "journal" in caplog.text.lower()
    # No traceback reaches the terminal for the clean-stop signal either.
    assert capsys.readouterr().err == ""


def test_non_json_bytes_exits_one_names_path_no_traceback(tmp_path, caplog, capsys):
    path = tmp_path / "status.json"
    path.write_bytes(b"\x00\x01not json at all{{{")

    with caplog.at_level("ERROR", logger="telemetry.ops.cli"):
        code = _call_status_cli(path)

    assert code == EXIT_ERROR
    assert str(path) in caplog.text
    assert "Traceback" not in caplog.text
    assert "Traceback" not in capsys.readouterr().err


def test_valid_json_missing_state_key_exits_one_names_path_no_traceback(tmp_path, caplog, capsys):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"written_at_monotonic": 1000.0, "extras": {}}))

    with caplog.at_level("ERROR", logger="telemetry.ops.cli"):
        code = _call_status_cli(path)

    assert code == EXIT_ERROR
    assert str(path) in caplog.text
    assert "Traceback" not in caplog.text
    assert "Traceback" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --json: exactly one stdout line, carrying the required fields; stdout
# stays clean enough for `telemetry-status --json | jq`.
# ---------------------------------------------------------------------------


def test_json_mode_emits_exactly_one_parseable_stdout_line_with_required_fields(tmp_path, capsys):
    path = tmp_path / "status.json"
    _write_status(path, state=STATE_CAPTURING, extras=_CAPTURING_EXTRAS)

    code = _call_status_cli(path, as_json=True)

    captured = capsys.readouterr()
    stdout_lines = captured.out.splitlines()
    assert len(stdout_lines) == 1
    payload = json.loads(stdout_lines[0])
    assert payload["state"] == STATE_CAPTURING
    assert payload["stale"] is False
    assert payload["staleness_reason"] is None
    assert payload["age_s"] == pytest.approx(0.5)
    assert payload["exit_code"] == EXIT_FRESH_OK
    assert code == EXIT_FRESH_OK


def test_json_mode_exit_code_field_reflects_staleness_precedence(tmp_path, capsys):
    path = tmp_path / "status.json"
    _write_status(path, state=STATE_CAPTURING, extras=_CAPTURING_EXTRAS, written_at=1_000.0)

    code = _call_status_cli(path, as_json=True, now_fn=lambda: 1_010.0, stale_after_s=5.0)

    payload = json.loads(capsys.readouterr().out.splitlines()[0])
    assert payload["stale"] is True
    assert payload["exit_code"] == EXIT_STALE
    assert code == EXIT_STALE
