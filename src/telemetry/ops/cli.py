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
plan produces, never the codes below):

- `0` -- fresh, and state in `{booting, waiting-for-hardware, capturing}`.
- `2` -- fresh, and state in `{degraded, stopped-error}`.
- `3` -- stale (any state).
- `4` -- no status file at the path: the logger is not running. This is the
  clean-stop signal, not an error -- `HeartbeatPublisher.remove()` on the
  writer side is what produces this condition on a clean exit.
- `1` -- the status file is present but unreadable/malformed, or the config
  itself could not be loaded.

**Two outputs, mirroring every other CLI in this codebase**
(`telemetry.logger.cli`, `telemetry.ground.cli`): `logging` goes to stderr,
for humans watching this process run. The actual *result* -- the rendered
state, whether human-readable text or the single `--json` line -- is
printed to stdout in both modes: this CLI's whole purpose is that result,
so unlike the write-side CLIs it is not reserved for a machine-only
consumer. `--json` additionally guarantees stdout carries exactly one line
and nothing else, so a script can parse it without filtering.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from telemetry.logger.config import LoggerConfig, LoggerConfigError, load_logger_config
from telemetry.ops.heartbeat import HeartbeatReadError, read_heartbeat

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


def _render_human(state: str, reading) -> str:
    lines = [
        f"state: {state}",
        f"age_s: {reading.age_s:.3f}",
        f"stale: {reading.stale}",
    ]
    if reading.staleness_reason is not None:
        lines.append(f"staleness_reason: {reading.staleness_reason}")
    detail = reading.payload.get("detail")
    if detail:
        lines.append(f"detail: {detail}")
    extras = reading.payload.get("extras") or {}
    if extras:
        lines.append("extras:")
        for key in sorted(extras):
            lines.append(f"  {key}: {extras[key]}")
    return "\n".join(lines)


def main(argv=None) -> None:
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
        # exit-code contract.
        logger.error(
            "no heartbeat file at %s -- the logger is not running", heartbeat_path
        )
        raise SystemExit(EXIT_NOT_RUNNING)

    try:
        reading = read_heartbeat(heartbeat_path, stale_after_s=stale_after_s)
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
                },
                sort_keys=True,
            )
        )
    else:
        print(_render_human(state, reading))

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
