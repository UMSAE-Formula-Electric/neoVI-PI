"""
telemetry.ground.simulate — a car stand-in (`python -m telemetry.ground.simulate`), GND-03/D-15.

**What this is.** A demonstration and manual-test tool: it drives DBC-shaped synthetic CAN traffic
through the exact same encode/batch/frame/link path the real car-side logger uses, so the pit
dashboard (`telemetry.ground.cli --serve`) stays demoable and manually testable with no car, no
neoVI hardware, and no radio present. Replaces the retired `can-dashboard/simulate.js`, which
re-implemented per-signal random-walk generation from scratch against a hardcoded signal list;
nothing here does that -- every value comes from `telemetry.synth.generator.SyntheticFrameSource`,
the same synthetic source `telemetry.logger.cli --source synthetic` already drives.

**What this is NOT.** It is not a test fixture for the car-side logger -- that already has its own
`--source synthetic` flag and needs no help from this module. It is not the no-hardware proof of
the full chain, either -- that proof is `tests/test_end_to_end.py`'s two-process test, which spawns
real logger and ground-station subprocesses. This module exists purely so a human can run a demo
and look at it.

**The real wire path, all of it reused, none of it re-implemented:**
`SyntheticFrameSource.frames()` -> `CapturedFrame` -> a bounded `collections.deque` (the same
bounded-deque shape `telemetry.capture.fanout.FanOut` gives the telemetry side on the car) ->
`telemetry.logger.pipeline.TelemetryPipeline` -> `telemetry.wire.encoder.Encoder` -> COBS+CRC
framing -> `Link.send()`. What the dashboard shows arrived exactly the way real telemetry will.

**Frames are paced in real time**, not delivered as one instantaneous burst: each frame is held
until the wall clock reaches its own offset from the first frame's timestamp (divided by
`--pacing`), so values change at their DBC-declared rates the way a real bus would. `--loop`
restarts the frame iteration and re-bases the pacing clock once it is exhausted, so a demo can run
for as long as someone is watching it.

**The car link, mirrored from the ground station's own documented role reversal.** This module's
`build_car_link` binds its own `(local_host, local_port)` and sends to `(remote_host,
remote_port)` -- exactly what `telemetry.logger.cli._build_link` already does for the real car,
and the mirror image of `telemetry.ground.cli._build_link`'s receive-only role reversal (which
binds the *remote* address because it only listens). `--link-kind loopback` is refused: an
in-process `LoopbackLink` only ever delivers to a `Link` instance constructed within THIS process,
so a `telemetry.ground.cli --serve` running as a genuinely separate process could never receive
anything from it -- the simulator would appear to run while sending into a void. Refusing here,
rather than constructing something that cannot work, is the fail-closed choice; a `udp` link is
what makes the two-terminal demo work.

**Testable without a subprocess.** `build_car_link` and `feed_frames` are each their own callable
function, independent of argument parsing -- `tests/test_ground_simulate.py` drives both directly
against a real `Deframer` and a recording `Link` stand-in, with no socket and no subprocess
involved.
"""

import argparse
import collections
import logging
import signal
import sys
import threading
import time
from dataclasses import replace
from typing import Callable, Deque, Optional

from telemetry.capture.fanout import CapturedFrame
from telemetry.link.base import Link
from telemetry.link.udp import UdpLink
from telemetry.logger.config import (
    VALID_LINK_KINDS,
    LoggerConfig,
    LoggerConfigError,
    load_logger_config,
)
from telemetry.logger.pipeline import TelemetryPipeline
from telemetry.measure.config import GateConfig, GateConfigError, load_gate_config
from telemetry.synth.entropy import BRACKET_NAMES
from telemetry.synth.generator import SyntheticFrameSource
from telemetry.wire.dictionary import DbcLoadError, build_id_dictionary, load_dbc
from telemetry.wire.encoder import Encoder

logger = logging.getLogger(__name__)

DEFAULT_BRACKET = "typical"
DEFAULT_PACING = 1.0
# How much synthetic data (in DBC-declared seconds) is generated when
# --duration-s is omitted -- mirrors telemetry.logger.cli's
# DEFAULT_SYNTHETIC_DURATION_S convention for its own --source synthetic mode.
DEFAULT_DURATION_S = 5.0
_SHUTDOWN_JOIN_TIMEOUT_S = 10.0


class UnreachableLinkKind(Exception):
    """Raised by `build_car_link` when `link_config.kind == 'loopback'` -- see the module
    docstring's "fail-closed" note. Never a `LoggerConfigError`: this is not a malformed config,
    it is a valid config value that this specific tool cannot use."""


def _configure_logging(level_name: str) -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level_name),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handle_signal(signum, _frame):
        logger.warning("received signal %s -- stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


def build_car_link(link_config) -> Link:
    """The CAR side of the link -- the mirror image of
    `telemetry.ground.cli._build_link`'s documented role reversal. That station binds the
    *remote* address because it only ever receives; this side binds its own `(local_host,
    local_port)` and sends to `(remote_host, remote_port)`, exactly what
    `telemetry.logger.cli._build_link` already does for the real car (deliberately built the same
    way here, not re-derived).

    Raises `UnreachableLinkKind` for `link.kind == 'loopback'` -- see the module docstring."""
    if link_config.kind == "loopback":
        raise UnreachableLinkKind(
            "link.kind='loopback' cannot drive telemetry.ground.simulate: an in-process "
            "LoopbackLink only ever delivers to a Link instance constructed within THIS "
            "process, so a `telemetry.ground.cli --serve` running as a separate process could "
            "never receive anything sent on it -- the simulator would appear to run while "
            "sending into a void. Use --link-kind udp (config/logger.json's own default) so "
            "the two-terminal demo actually works."
        )
    if link_config.kind == "udp":
        return UdpLink(
            local_addr=(link_config.udp.local_host, link_config.udp.local_port),
            remote_addr=(link_config.udp.remote_host, link_config.udp.remote_port),
            recv_bufsize=link_config.udp.recv_bufsize,
        )
    # Unreachable in practice -- telemetry.logger.config already restricts
    # link.kind to VALID_LINK_KINDS at load time.
    raise LoggerConfigError(
        f"link.kind={link_config.kind!r} is not one of {sorted(VALID_LINK_KINDS)}"
    )


def feed_frames(
    *,
    frame_source: SyntheticFrameSource,
    telemetry_queue: "Deque[CapturedFrame]",
    channel_name: str,
    stop_event: threading.Event,
    pacing: float = DEFAULT_PACING,
    loop: bool = False,
    now_fn: Callable[[], float] = time.monotonic,
) -> int:
    """Iterate `frame_source.frames()`, pacing each frame in real time relative to the first
    frame's own timestamp: a frame whose DBC-declared timestamp is `offset_us` after the first
    frame's is held until the wall clock reaches `start + offset_us / 1e6 / pacing`, then wrapped
    in a `CapturedFrame` tagged `channel_name` and appended to `telemetry_queue` -- the same
    channel-tagging choice `telemetry.logger.cli` documents for its own synthetic mode, since the
    synthetic source models per-message rate and entropy rather than per-bus separation, and the
    channel tag never crosses the wire (the ground station derives channel from the DBC).

    `stop_event` is checked before every sleep and before every append, via
    `threading.Event.wait` as the sleep primitive, so the caller is always promptly killable and
    a pacing bug can never leave this function unresponsive to a stop request.

    With `loop=True`, once `frame_source.frames()` is exhausted, iteration restarts and the
    pacing clock re-bases to a fresh wall-clock start -- `SyntheticFrameSource.frames()` rebuilds
    its own deterministic mutator/event state from scratch on every call, so this is safe to call
    repeatedly. Returns the total number of frames fed (useful for the shutdown summary and for
    tests asserting real work happened)."""
    frames_fed = 0

    while not stop_event.is_set():
        wall_clock_start = now_fn()
        first_frame_timestamp_us: Optional[int] = None

        for raw_frame in frame_source.frames():
            if stop_event.is_set():
                break

            if first_frame_timestamp_us is None:
                first_frame_timestamp_us = raw_frame.timestamp_us

            offset_s = (raw_frame.timestamp_us - first_frame_timestamp_us) / 1_000_000.0
            target_wall_clock = wall_clock_start + offset_s / pacing
            remaining = target_wall_clock - now_fn()
            if remaining > 0:
                stop_event.wait(timeout=remaining)
            if stop_event.is_set():
                break

            telemetry_queue.append(CapturedFrame(channel=channel_name, frame=raw_frame))
            frames_fed += 1

        if not loop:
            break

    return frames_fed


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "A car stand-in: drives DBC-shaped synthetic CAN traffic through the real "
            "encode/batch/frame/link path into a running ground station "
            "(`python -m telemetry.ground.cli --serve`) -- so the dashboard stays demoable and "
            "manually testable with no car, no neoVI hardware, and no radio present (GND-03, "
            "D-15)."
        )
    )
    parser.add_argument(
        "--config",
        default=str(LoggerConfig.default_path()),
        help=(
            "Path to the logger config (default: config/logger.json) -- the SAME file the "
            "ground station reads, so both sides agree on the dictionary and allowlist."
        ),
    )
    parser.add_argument(
        "--link-kind",
        default=None,
        choices=sorted(VALID_LINK_KINDS),
        help=(
            "Override link.kind from the config. 'loopback' is refused (see module docstring) "
            "-- use 'udp' (config/logger.json's own default) for the two-terminal demo."
        ),
    )
    parser.add_argument(
        "--bracket",
        default=DEFAULT_BRACKET,
        choices=list(BRACKET_NAMES),
        help=f"Entropy bracket to drive (default {DEFAULT_BRACKET}).",
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=None,
        help=(
            "Bound how much synthetic data is generated, in DBC-declared seconds (default "
            f"{DEFAULT_DURATION_S}s). With --pacing 1.0 (the default) the real wall-clock run "
            "time is approximately this many seconds; --pacing scales that."
        ),
    )
    parser.add_argument(
        "--pacing",
        type=float,
        default=DEFAULT_PACING,
        help=(
            f"Real-time pacing multiplier (default {DEFAULT_PACING}): 1.0 plays frames at their "
            "DBC-declared rate; >1.0 plays faster (shorter real-time runs); <1.0 plays slower."
        ),
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help=(
            "Restart the frame iteration, re-basing the pacing clock, once it is exhausted -- "
            "so a demo can run for as long as someone is watching it. Without this flag the "
            "simulator exits once the generated data is exhausted."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    args = parser.parse_args(argv)
    if args.pacing <= 0:
        parser.error(f"--pacing must be > 0, got {args.pacing!r}")
    return args


def _apply_overrides(config: LoggerConfig, args: argparse.Namespace) -> LoggerConfig:
    if args.link_kind is not None:
        config = replace(config, link=replace(config.link, kind=args.link_kind))
    return config


def main(argv=None) -> None:
    args = _parse_args(argv)
    _configure_logging(args.log_level)

    stop_event = threading.Event()
    # Installed before any resource is constructed, mirroring
    # telemetry.logger.cli and telemetry.ground.cli's own ordering.
    _install_signal_handlers(stop_event)

    try:
        config = load_logger_config(args.config)
    except LoggerConfigError as exc:
        logger.error("failed to load logger config at %s: %s", args.config, exc)
        raise SystemExit(1) from exc

    config = _apply_overrides(config, args)

    try:
        db = load_dbc(config.dbc_path)
    except DbcLoadError as exc:
        logger.error("failed to load DBC: %s", exc)
        raise SystemExit(1) from exc

    dictionary = build_id_dictionary(db, config.dbc_path)

    try:
        gate_config = load_gate_config(GateConfig.default_path())
    except GateConfigError as exc:
        logger.error("failed to load gate config: %s", exc)
        raise SystemExit(1) from exc

    try:
        link = build_car_link(config.link)
    except UnreachableLinkKind as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    duration_s = args.duration_s if args.duration_s is not None else DEFAULT_DURATION_S
    frame_source = SyntheticFrameSource(
        db=db,
        dictionary=dictionary,
        config=gate_config,
        bracket_name=args.bracket,
        duration_s=duration_s,
        only_message_names=config.telemetry.allowlist,
    )

    encoder = Encoder(dictionary)
    telemetry_queue: "Deque[CapturedFrame]" = collections.deque(
        maxlen=config.telemetry.queue_depth
    )
    pipeline = TelemetryPipeline(
        telemetry_queue=telemetry_queue,
        encoder=encoder,
        link=link,
        dict_version=dictionary.dict_version,
        batch_frames=config.telemetry.batch_frames,
        batch_max_age_s=config.telemetry.batch_max_age_s,
        stop_event=stop_event,
    )
    pipeline.start()

    logger.info(
        "simulator started: bracket=%s duration_s=%.1f pacing=%.2f loop=%s "
        "allowlist_messages=%d",
        args.bracket,
        duration_s,
        args.pacing,
        args.loop,
        len(config.telemetry.allowlist),
    )

    frames_fed = 0
    try:
        frames_fed = feed_frames(
            frame_source=frame_source,
            telemetry_queue=telemetry_queue,
            channel_name=config.channels[0].name,
            stop_event=stop_event,
            pacing=args.pacing,
            loop=args.loop,
        )
    finally:
        stop_event.set()
        pipeline.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)
        link.close()

    logger.info(
        "simulator stopped: frames_fed=%d batches_sent=%d bytes_sent=%d "
        "unknown_id=%d payload_too_long=%d framing_errors=%d link_send_failures=%d",
        frames_fed,
        pipeline.counters.batches_sent,
        pipeline.counters.bytes_sent,
        pipeline.counters.unknown_id_count,
        pipeline.counters.payload_too_long_count,
        pipeline.counters.framing_error_count,
        pipeline.counters.link_send_failure_count,
    )


if __name__ == "__main__":
    main()
