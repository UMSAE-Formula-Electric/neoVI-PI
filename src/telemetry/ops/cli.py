"""
telemetry.ops.cli -- `telemetry-status` (`python -m telemetry.ops.cli`),
the separate reader process (OPS-02) a human standing at the car runs to
answer "is the logger alive and capturing" without opening a terminal on
the logger itself.

**Deliberately a different process from the writer.** `telemetry.logger.cli`
publishes the heartbeat; this module only ever reads it. "Legible to
someone standing at the car" implies a human runs this on demand, not that
the logger's own stdout is the interface.

**Exit-code contract, defined here once** (03-05 widens the rendering this
module produces, never the codes below):

- `0` -- fresh, and state in `{booting, waiting-for-hardware, capturing}`.
- `2` -- fresh, and state in `{degraded, stopped-error}`.
- `3` -- stale (any state) -- staleness always outranks state, in both the
  headline and the exit code: a status file frozen mid-`capturing` must
  never read as healthy just because its last recorded state was good news
  (03-RESEARCH.md Pitfall 5).
- `4` -- no status file at the path: the logger is not running. This is the
  clean-stop signal, not an error -- `HeartbeatPublisher.remove()` on the
  writer side is what produces this condition on a clean exit.
- `1` -- the status file is present but unreadable/malformed, or the config
  itself could not be loaded.

**Two outputs, corrected in 03-05 to match every other CLI in this
codebase** (`telemetry.logger.cli`, `telemetry.ground.cli`): stdout is
reserved exclusively for the single `--json` line when `--json` is passed,
and carries nothing at all otherwise. Every human-readable line -- the
plain-text rendering below AND ordinary `logging` output -- goes to
stderr, so `telemetry-status --json | jq` works, matching this project's
fixed stdout/stderr split (`.claude/CLAUDE.md`'s Logging section: stdout
reserved for machine-readable output, humans get stderr). 03-01 originally
printed the human-readable report to stdout too, reasoning that the report
itself was this CLI's "whole purpose"; 03-05 corrects that carve-out to
match the rest of this codebase -- a human at a terminal reads stderr just
as readily as stdout, and a script piping `--json` output should never
have to filter anything out of stdout.

**Five states, one meaning and one next action each, never a silently
blank rendering for a sixth.** `_STATE_INFO` is keyed by the exact names in
`telemetry.ops.heartbeat.HEARTBEAT_STATES`; a mismatch between the two
raises at import time (below), not at render time -- 03-07's runbook
generates its own troubleshooting table from the same five names, and the
two must never silently drift apart.

**Staleness leads the headline, not just the exit code.** A stale reading
renders its age and reason first, names the state it was last in second,
and never lets a reassuring-sounding last-known state read as current
health -- the exact false-negative 03-RESEARCH.md Pitfall 5 warns about.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple

from telemetry.logger.config import LoggerConfig, LoggerConfigError, load_logger_config
from telemetry.ops.heartbeat import (
    HEARTBEAT_STATES,
    STATE_CAPTURING,
    STATE_DEGRADED,
    HeartbeatReadError,
    HeartbeatReading,
    read_heartbeat,
)

logger = logging.getLogger(__name__)

EXIT_FRESH_OK = 0
EXIT_FRESH_BAD = 2
EXIT_STALE = 3
EXIT_NOT_RUNNING = 4
EXIT_ERROR = 1

# States that mean "fresh is good news" vs. "fresh but bad news" -- staleness
# (any state) always overrides both and maps to EXIT_STALE.
_FRESH_OK_STATES = frozenset({"booting", "waiting-for-hardware", "capturing"})
_FRESH_BAD_STATES = frozenset({"degraded", "stopped-error"})

# One (meaning, next_action) pair per state, keyed by the exact names in
# HEARTBEAT_STATES -- validated against that tuple immediately below, so a
# sixth state landing there with no entry here fails at import, not at
# render time.
_STATE_INFO: Dict[str, Tuple[str, str]] = {
    "booting": (
        "the logger has started and is loading its configuration and DBC.",
        "expected to last well under a second -- if it persists, check the "
        "journal (journalctl -u telemetry-logger) for the reason.",
    ),
    "waiting-for-hardware": (
        "the logger is alive and retrying -- the CAN bus is most likely "
        "not powered yet.",
        "this is the normal power-up sequence on this car, not a fault; it "
        "clears by itself once the bus comes up.",
    ),
    "capturing": (
        "the logger is recording.",
        "read the evidence line below to confirm frames are actually moving.",
    ),
    "degraded": (
        "still recording, but something needs attention.",
        "see the detail line below for what.",
    ),
    "stopped-error": (
        "the logger stopped and did not finish cleanly -- this session's "
        "archive will have no completion marker.",
        "check the journal (journalctl -u telemetry-logger) for the reason.",
    ),
}

_missing_state_info = set(HEARTBEAT_STATES) - set(_STATE_INFO)
if _missing_state_info:
    # A hard failure at import, not a silently blank rendering -- see the
    # module docstring's "Five states" note. 03-07's runbook table is
    # generated from these same five names and must never silently drift
    # from this mapping.
    raise RuntimeError(
        "telemetry.ops.cli._STATE_INFO is missing entries for "
        f"{sorted(_missing_state_info)} present in "
        "telemetry.ops.heartbeat.HEARTBEAT_STATES -- add meaning/next-action "
        "text before shipping a new heartbeat state"
    )

# The extras keys telemetry.logger.cli's capturing/degraded snapshot
# closure actually writes (src/telemetry/logger/cli.py's `_capturing_
# snapshot`) -- read fresh against that closure, not assumed from a name
# that merely sounds right ("frames_captured"/"frames_archived" do not
# exist on the wire; "frames_submitted"/"records_written" do). A rename on
# either side silently empties the evidence line below, which is exactly
# what 03-07's runbook coverage test pins against.
_EXTRAS_KEY_SESSION_NAME = "session_name"
_EXTRAS_KEY_FRAMES_PER_S = "frames_per_s"
_EXTRAS_KEY_FRAMES_CAPTURED = "frames_submitted"
_EXTRAS_KEY_FRAMES_ARCHIVED = "records_written"


def _configure_logging(level_name: str) -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level_name),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "telemetry-status: reads the car-side logger's most recent "
            "heartbeat and reports its state and staleness for a human "
            "standing at the car -- a separate process from the logger "
            "itself (OPS-02)."
        )
    )
    parser.add_argument(
        "--config",
        default=str(LoggerConfig.default_path()),
        help="Path to the logger config (default: config/logger.json).",
    )
    parser.add_argument(
        "--heartbeat-path",
        default=None,
        help="Override ops.heartbeat_path from the config.",
    )
    parser.add_argument(
        "--stale-after-s",
        type=float,
        default=None,
        help="Override ops.heartbeat_stale_after_s from the config.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit exactly one JSON line on stdout instead of human-readable text.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    return parser.parse_args(argv)


def _exit_code_for(state: str, stale: bool) -> int:
    """The exit-code contract from the module docstring. An unrecognised
    state (should be unreachable -- `HEARTBEAT_STATES` is closed) falls
    into the same bucket as unreadable/malformed content: never guessed
    at, never silently mapped to a "good" code."""
    if stale:
        return EXIT_STALE
    if state in _FRESH_OK_STATES:
        return EXIT_FRESH_OK
    if state in _FRESH_BAD_STATES:
        return EXIT_FRESH_BAD
    return EXIT_ERROR


def _render_evidence_line(extras: Mapping[str, object]) -> Optional[str]:
    """The concrete evidence behind the word `capturing` (and `degraded`,
    which is still recording): session name, frames/s, and frames captured
    versus archived, read from the exact `extras` keys
    `telemetry.logger.cli`'s capturing closure writes. Returns `None` if
    none of those keys are present, so a reading that legitimately carries
    no evidence (e.g. most `stopped-error` extras) never renders an
    evidence line with nothing behind it."""
    keys = (
        _EXTRAS_KEY_SESSION_NAME,
        _EXTRAS_KEY_FRAMES_PER_S,
        _EXTRAS_KEY_FRAMES_CAPTURED,
        _EXTRAS_KEY_FRAMES_ARCHIVED,
    )
    if not any(key in extras for key in keys):
        return None

    session_name = extras.get(_EXTRAS_KEY_SESSION_NAME, "?")
    frames_per_s = extras.get(_EXTRAS_KEY_FRAMES_PER_S)
    frames_per_s_str = (
        f"{frames_per_s:.1f}" if isinstance(frames_per_s, (int, float)) else "?"
    )
    frames_captured = extras.get(_EXTRAS_KEY_FRAMES_CAPTURED, "?")
    frames_archived = extras.get(_EXTRAS_KEY_FRAMES_ARCHIVED, "?")
    return (
        f"evidence: session={session_name} frames/s={frames_per_s_str} "
        f"frames_captured={frames_captured} frames_archived={frames_archived}"
    )


def _render_stale(reading: HeartbeatReading) -> str:
    """Staleness leads the headline, ahead of the state it was last in --
    see the module docstring's exit-code contract and 03-RESEARCH.md
    Pitfall 5. `clock-went-backwards` gets its own words, written for a
    non-author: the file's age cannot be trusted because the machine has
    rebooted since it was written, not because the logger simply went
    quiet -- the reboot-boundary hazard `telemetry.ops.heartbeat` guards
    against."""
    state = reading.payload.get("state")
    reason = reading.staleness_reason
    lines = [
        f"STALE ({reason}) -- last known state was {state!r}, "
        f"age_s={reading.age_s:.3f}"
    ]
    if reason == "clock-went-backwards":
        lines.append(
            "the machine appears to have rebooted since this file was "
            "written, so its age cannot be trusted. a running logger "
            "rewrites this file within a second of starting -- if it has "
            "not, treat the logger as not running."
        )
    elif reason == "implausible-age":
        lines.append(
            "this file is far older than any real gap between heartbeat "
            "writes should ever be -- the process that wrote it is very "
            "likely gone."
        )
    else:
        lines.append(
            "the logger has not updated this file recently enough to "
            "trust -- it may have crashed, hung, or stopped writing."
        )
    return "\n".join(lines)


def _render_fresh(reading: HeartbeatReading) -> str:
    state = reading.payload.get("state")
    meaning, next_action = _STATE_INFO.get(
        state,
        (
            f"unrecognised state {state!r} -- this build of telemetry-status "
            "does not know what it means.",
            "check that telemetry-status and telemetry-logger are the same "
            "version.",
        ),
    )
    lines = [f"state: {state}", meaning, f"next: {next_action}"]
    detail = reading.payload.get("detail")
    if detail:
        lines.append(f"detail: {detail}")
    if state in (STATE_CAPTURING, STATE_DEGRADED):
        evidence = _render_evidence_line(reading.payload.get("extras") or {})
        if evidence is not None:
            lines.append(evidence)
    return "\n".join(lines)


def _render_human(reading: HeartbeatReading) -> str:
    if reading.stale:
        return _render_stale(reading)
    return _render_fresh(reading)


def main(
    argv=None,
    *,
    now_fn: Callable[[], float] = time.monotonic,
) -> None:
    args = _parse_args(argv)
    _configure_logging(args.log_level)

    try:
        config = load_logger_config(args.config)
    except LoggerConfigError as exc:
        logger.error("failed to load logger config at %s: %s", args.config, exc)
        raise SystemExit(EXIT_ERROR) from exc

    heartbeat_path = (
        Path(args.heartbeat_path)
        if args.heartbeat_path is not None
        else config.ops.heartbeat_path
    )
    stale_after_s = (
        args.stale_after_s
        if args.stale_after_s is not None
        else config.ops.heartbeat_stale_after_s
    )

    if not heartbeat_path.exists():
        # The clean-stop signal, not an error -- see the module docstring's
        # exit-code contract. Also names the asymmetry 03-04 created: a
        # *running* service with no status file at all means its config
        # failed to parse before the heartbeat path was even known -- the
        # journal, not this file, has that reason.
        logger.error(
            "no heartbeat file at %s -- if telemetry-logger is not running, "
            "this is expected (a clean stop removes this file); if the "
            "service IS running with no file here at all, its config "
            "failed to parse before the heartbeat path was known -- "
            "journalctl -u telemetry-logger has the reason",
            heartbeat_path,
        )
        raise SystemExit(EXIT_NOT_RUNNING)

    try:
        reading = read_heartbeat(
            heartbeat_path, stale_after_s=stale_after_s, now_fn=now_fn
        )
    except HeartbeatReadError as exc:
        logger.error("heartbeat at %s could not be read: %s", heartbeat_path, exc)
        raise SystemExit(EXIT_ERROR) from exc

    state = reading.payload.get("state")
    exit_code = _exit_code_for(state, reading.stale)

    if args.json:
        print(
            json.dumps(
                {
                    "state": state,
                    "detail": reading.payload.get("detail"),
                    "age_s": reading.age_s,
                    "stale": reading.stale,
                    "staleness_reason": reading.staleness_reason,
                    "extras": reading.payload.get("extras") or {},
                    "exit_code": exit_code,
                },
                sort_keys=True,
            )
        )
    else:
        # Corrected in 03-05 -- see module docstring: stdout is reserved
        # solely for the --json line; the human-readable report goes to
        # stderr, alongside every other log line this process emits.
        print(_render_human(reading), file=sys.stderr)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
