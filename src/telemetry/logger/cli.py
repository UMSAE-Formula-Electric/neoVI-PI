"""
telemetry.logger.cli — the car-side entry point (`python -m telemetry.logger.cli`).

Wires together every piece Phase 1 built into one runnable process: capture
(hardware or synthetic), fan-out (`telemetry.capture.fanout.FanOut`), the
durable archive (`telemetry.archive.runner.ArchiveRunner` +
`telemetry.archive.writer.ArchiveWriter`), and the live link
(`telemetry.logger.pipeline.TelemetryPipeline`) — driven entirely from
`config/logger.json` (OPS-05), with CLI flags overriding individual fields
and no source edit needed to change any setting. Phase 3's unattended-boot
work supervises this one process.

**This is the single place logging is configured** (`_configure_logging`)
— no library module under `telemetry` may configure logging itself, per
`01-CONTEXT.md`'s established convention (stderr for humans, stdout
reserved for machine-readable output).

**Two frame sources.** `--source hardware` (the default) polls the attached
neoVI device via `telemetry.capture.hardware_source.HardwareFrameSource`.
`--source synthetic` drives `telemetry.synth.generator.SyntheticFrameSource`
so the whole process is runnable and testable with no device attached — not
a test fixture bolted on, but how anyone demonstrates the logger on a
laptop and how the 01-13 soak test drives real code. The synthetic
generator models per-message rate and entropy, not per-bus separation, so
every synthetic frame is tagged with the first configured channel — a
documented limit of demonstrating a single-source generator against a
dual-bus config, not a claim that it models both buses.

**Wiring order:** load and validate config, load the DBC, resolve the
telemetry allowlist, create the session, open the archive writer, build the
link/fan-out/archive-runner/telemetry-pipeline, start both consumer
threads, then run the capture loop on the main thread. **Signal handlers
for interrupt and terminate are installed before any of that** — before
config is even loaded — mirroring `src/new_logger.py`'s ordering (lines
329-332): a signal arriving during startup must never leave a half-built
process with an open archive and no way to unwind it.

**Shutdown is strict order:** stop capture (the stop event, which both
frame sources honour), best-effort-push the archive runner's sentinel,
join the archive runner (drains the queue and flushes the writer) and the
telemetry pipeline (flushes its batch in progress), close the link, close
the writer, then call `mark_done` — **only if the archive closed cleanly**.
An interrupted or failed session is left without its `.done` marker on
purpose; that distinction is the whole of ARCH-05.

**Two outputs at shutdown**, both from the same counters so a human and a
future health check read identical numbers: a human-readable report to
stderr, and one line of machine-readable JSON to stdout (CAP-05/CAP-06).
Nothing else is ever written to stdout.

Deliberately does NOT carry over `src/new_logger.py`'s hardcoded transmit
configuration or its commented-out alternative code paths — nothing in
Phase 1 transmits on the CAN bus, and dead commented code is an
anti-pattern this project does not continue.

**Phase 3 (OPS-02): publishes a heartbeat status file at 1 Hz** via
`telemetry.ops.heartbeat.HeartbeatPublisher`, so a second process
(`telemetry.ops.cli`, `telemetry-status`) can answer "is the logger alive
and capturing" without opening a terminal on this process. Constructed
immediately after config load/override in `main()` — the earliest point
`config.ops.heartbeat_path` is known — and published once synchronously as
`booting` before any other resource exists; `_run_session` reassigns its
`snapshot_fn` to read the real counters and starts the periodic thread only
once the archive runner and telemetry pipeline are already running. The
heartbeat never re-derives or re-counts anything the existing counter
dataclasses already own (03-CONTEXT.md). On a clean exit the status file
is removed — its absence, not a sixth state, is what says "not running".
"""

import argparse
import json
import logging
import queue
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

from telemetry.archive.runner import STOP as ARCHIVE_RUNNER_STOP
from telemetry.archive.runner import ArchiveRunner
from telemetry.archive.session import mark_done, new_session
from telemetry.archive.writer import ArchiveWriter
from telemetry.capture.fanout import CapturedFrame, FanOut
from telemetry.capture.hardware_source import HardwareFrameSource
from telemetry.link.base import Link
from telemetry.link.loopback import LoopbackLink
from telemetry.link.udp import UdpLink
from telemetry.logger.config import (
    VALID_LINK_KINDS,
    LoggerConfig,
    LoggerConfigError,
    load_logger_config,
    resolve_allowlist,
)
from telemetry.logger.pipeline import TelemetryPipeline
from telemetry.measure.config import GateConfig, GateConfigError, load_gate_config
from telemetry.ops.heartbeat import (
    STATE_BOOTING,
    STATE_CAPTURING,
    HeartbeatPublisher,
    HeartbeatSnapshot,
)
from telemetry.synth.entropy import BRACKET_NAMES
from telemetry.synth.generator import SyntheticFrameSource
from telemetry.wire.dictionary import DbcLoadError, build_id_dictionary, load_dbc
from telemetry.wire.encoder import Encoder

logger = logging.getLogger(__name__)

DEFAULT_SYNTHETIC_DURATION_S = 5.0
DEFAULT_BRACKET = "typical"
_SHUTDOWN_JOIN_TIMEOUT_S = 10.0


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


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "The car-side telemetry logger: captures both CAN buses, "
            "writes every frame to a durable MCAP archive, and "
            "simultaneously streams the critical-channel subset over a "
            "configured link -- driven entirely from config/logger.json, "
            "with no source edit needed to change any setting."
        )
    )
    parser.add_argument(
        "--config",
        default=str(LoggerConfig.default_path()),
        help="Path to the logger config (default: config/logger.json).",
    )
    parser.add_argument(
        "--archive-root",
        default=None,
        help="Override archive.root_dir from the config.",
    )
    parser.add_argument(
        "--link-kind",
        default=None,
        choices=sorted(VALID_LINK_KINDS),
        help="Override link.kind from the config.",
    )
    parser.add_argument(
        "--heartbeat-path",
        default=None,
        help="Override ops.heartbeat_path from the config (OPS-02).",
    )
    parser.add_argument(
        "--source",
        default="hardware",
        choices=["hardware", "synthetic"],
        help=(
            "Frame source: 'hardware' polls the attached neoVI device "
            "(default). 'synthetic' drives "
            "telemetry.synth.generator.SyntheticFrameSource so the whole "
            "process is runnable and testable with no device attached."
        ),
    )
    parser.add_argument(
        "--bracket",
        default=DEFAULT_BRACKET,
        choices=list(BRACKET_NAMES),
        help="Entropy bracket for --source synthetic (ignored otherwise).",
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=None,
        help=(
            "Bound the run to N seconds (default: run until interrupted). "
            "For --source synthetic, also bounds how much data is "
            f"generated (default {DEFAULT_SYNTHETIC_DURATION_S}s if this "
            "flag is omitted with --source synthetic)."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    return parser.parse_args(argv)


def _apply_overrides(config: LoggerConfig, args: argparse.Namespace) -> LoggerConfig:
    """Individual CLI flags override individual config fields; everything
    not overridden comes from the file (OPS-05, 01-CONTEXT.md's locked
    decision)."""
    if args.archive_root is not None:
        config = replace(
            config,
            archive=replace(config.archive, root_dir=Path(args.archive_root).resolve()),
        )
    if args.link_kind is not None:
        config = replace(config, link=replace(config.link, kind=args.link_kind))
    if args.heartbeat_path is not None:
        config = replace(
            config,
            ops=replace(config.ops, heartbeat_path=Path(args.heartbeat_path).resolve()),
        )
    return config


def _build_link(link_config) -> Link:
    if link_config.kind == "loopback":
        return LoopbackLink()
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


def _synthetic_frame_iterator(*, db, dictionary, gate_config, bracket_name, duration_s, channel_name):
    """Wraps `SyntheticFrameSource.frames()` with a fixed channel tag -- see
    the module docstring's note on why every synthetic frame carries the
    same channel."""
    source = SyntheticFrameSource(
        db=db,
        dictionary=dictionary,
        config=gate_config,
        bracket_name=bracket_name,
        duration_s=duration_s,
    )
    for raw_frame in source.frames():
        yield CapturedFrame(channel=channel_name, frame=raw_frame)


def _build_summary(
    *,
    session,
    config: LoggerConfig,
    args: argparse.Namespace,
    fan_out_counters,
    pipeline_counters,
    writer: ArchiveWriter,
    hardware_counters,
    marked_done: bool,
    elapsed_s: float,
) -> dict:
    summary = {
        "session_name": session.session_name,
        "session_dir": str(session.directory),
        "naming_source": session.naming_source,
        "config_hash": config.config_hash,
        "config_path": str(args.config),
        "source": args.source,
        "link_kind": config.link.kind,
        "duration_s": elapsed_s,
        "archive_marked_done": marked_done,
        "frames_captured": fan_out_counters.frames_submitted,
        "frames_archived": writer.records_written,
        # CAP-03: the archive queue never silently drops -- a full queue is
        # fatal and stops the session instead of losing a frame quietly, so
        # this is a structural fact, not a derived count.
        "archive_drops": 0,
        "archive_overflow": fan_out_counters.archive_overflow,
        "archive_write_failure": fan_out_counters.archive_write_failure,
        "archive_high_water_mark": fan_out_counters.archive_high_water_mark,
        "telemetry_high_water_mark": fan_out_counters.telemetry_high_water_mark,
        "telemetry_discard_count": fan_out_counters.telemetry_discard_count,
        "telemetry_filtered_count": fan_out_counters.telemetry_filtered_count,
        "telemetry_unknown_id_count": fan_out_counters.telemetry_unknown_id_count,
        "telemetry_payload_too_long_count": fan_out_counters.telemetry_payload_too_long_count,
        "telemetry_unexpected_error_count": fan_out_counters.telemetry_unexpected_error_count,
        "telemetry_error_log_suppressed_count": fan_out_counters.telemetry_error_log_suppressed_count,
        "pipeline_frames_sent": pipeline_counters.frames_sent,
        "pipeline_batches_sent": pipeline_counters.batches_sent,
        "pipeline_bytes_sent": pipeline_counters.bytes_sent,
        "pipeline_unknown_id_count": pipeline_counters.unknown_id_count,
        "pipeline_payload_too_long_count": pipeline_counters.payload_too_long_count,
        "pipeline_unexpected_cfr_error_count": pipeline_counters.unexpected_cfr_error_count,
        "pipeline_framing_error_count": pipeline_counters.framing_error_count,
        "pipeline_link_send_failure_count": pipeline_counters.link_send_failure_count,
    }
    if hardware_counters is not None:
        summary["hardware_poll_count"] = hardware_counters.poll_count
        summary["hardware_error_count"] = hardware_counters.hardware_error_count
        summary["hardware_poll_exception_count"] = hardware_counters.poll_exception_count
        summary["hardware_excluded_message_count"] = hardware_counters.excluded_message_count
    return summary


def _log_human_summary(summary: dict) -> None:
    logger.info("=== session %s summary ===", summary["session_name"])
    logger.info(
        "frames captured=%d archived=%d archive_drops=%d",
        summary["frames_captured"],
        summary["frames_archived"],
        summary["archive_drops"],
    )
    logger.info(
        "archive high-water=%d telemetry high-water=%d telemetry "
        "discards=%d filtered=%d",
        summary["archive_high_water_mark"],
        summary["telemetry_high_water_mark"],
        summary["telemetry_discard_count"],
        summary["telemetry_filtered_count"],
    )
    logger.info(
        "telemetry pipeline: sent=%d batches=%d bytes=%d unknown_id=%d "
        "payload_too_long=%d unexpected_cfr=%d framing_errors=%d "
        "link_send_failures=%d",
        summary["pipeline_frames_sent"],
        summary["pipeline_batches_sent"],
        summary["pipeline_bytes_sent"],
        summary["pipeline_unknown_id_count"],
        summary["pipeline_payload_too_long_count"],
        summary["pipeline_unexpected_cfr_error_count"],
        summary["pipeline_framing_error_count"],
        summary["pipeline_link_send_failure_count"],
    )
    logger.info(
        "fan-out telemetry-path errors: unknown_id=%d payload_too_long=%d "
        "unexpected=%d log_suppressed=%d",
        summary["telemetry_unknown_id_count"],
        summary["telemetry_payload_too_long_count"],
        summary["telemetry_unexpected_error_count"],
        summary["telemetry_error_log_suppressed_count"],
    )
    if summary["archive_overflow"] or summary["archive_write_failure"]:
        logger.critical(
            "archive_overflow=%s archive_write_failure=%s -- "
            "archive_marked_done=%s",
            summary["archive_overflow"],
            summary["archive_write_failure"],
            summary["archive_marked_done"],
        )
    else:
        logger.info("archive_marked_done=%s", summary["archive_marked_done"])


def _run_session(config, args, db, dictionary, allowlist, stop_event, publisher) -> int:
    """Everything from session creation through shutdown and the summary
    report. Returns the process exit code: 0 normally, 1 if the archive did
    not close cleanly (the session is left without its `.done` marker)."""
    start_t = time.monotonic()

    session = new_session(config.archive.root_dir, config_hash=config.config_hash)
    logger.info(
        "session %s created at %s (naming_source=%s)",
        session.session_name,
        session.directory,
        session.naming_source,
    )

    writer = ArchiveWriter(
        session.mcap_path,
        channel_names=[c.name for c in config.channels],
        flush_every_records=config.archive.flush_every_records,
        flush_every_s=config.archive.flush_every_s,
    )
    link = _build_link(config.link)
    fan_out = FanOut(
        archive_maxsize=config.archive.queue_depth,
        telemetry_maxsize=config.telemetry.queue_depth,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
        dictionary=dictionary,
    )
    encoder = Encoder(dictionary)
    archive_runner = ArchiveRunner(
        archive_queue=fan_out.archive_queue,
        writer=writer,
        counters=fan_out.counters,
        stop_event=stop_event,
    )
    telemetry_pipeline = TelemetryPipeline(
        telemetry_queue=fan_out.telemetry_queue,
        encoder=encoder,
        link=link,
        dict_version=dictionary.dict_version,
        batch_frames=config.telemetry.batch_frames,
        batch_max_age_s=config.telemetry.batch_max_age_s,
        stop_event=stop_event,
    )

    archive_runner.start()
    telemetry_pipeline.start()

    # From here on the process is genuinely capturing (OPS-02) -- reassign
    # the publisher's snapshot_fn from the `booting` closure `main()`
    # installed to one that reads the real counters, then start the
    # periodic thread. `frames_per_s` is computed as the delta in
    # `frames_submitted` since the previous tick over the elapsed monotonic
    # interval -- never re-derived from a second frame count, per
    # `03-CONTEXT.md`'s "the heartbeat READS these, it does not re-derive
    # them". A parked car legitimately reports 0 frames/s; that is not a
    # fault state, so it is surfaced as a plain number in `extras`, never
    # mapped to `degraded` (03-03's terminal-state work owns that).
    _heartbeat_tick_state = {
        "frames_submitted": fan_out.counters.frames_submitted,
        "monotonic": time.monotonic(),
    }

    def _capturing_snapshot() -> HeartbeatSnapshot:
        now = time.monotonic()
        elapsed = now - _heartbeat_tick_state["monotonic"]
        current = fan_out.counters.frames_submitted
        frames_per_s = (
            (current - _heartbeat_tick_state["frames_submitted"]) / elapsed
            if elapsed > 0
            else 0.0
        )
        _heartbeat_tick_state["frames_submitted"] = current
        _heartbeat_tick_state["monotonic"] = now
        return HeartbeatSnapshot(
            state=STATE_CAPTURING,
            detail=None,
            extras={
                "session_name": session.session_name,
                "frames_submitted": fan_out.counters.frames_submitted,
                "records_written": writer.records_written,
                "frames_sent": telemetry_pipeline.counters.frames_sent,
                "archive_write_failure": fan_out.counters.archive_write_failure,
                "archive_overflow": fan_out.counters.archive_overflow,
                "frames_per_s": frames_per_s,
            },
        )

    publisher.snapshot_fn = _capturing_snapshot
    publisher.start()

    hardware_counters = None
    watchdog: Optional[threading.Timer] = None
    try:
        if args.source == "hardware":
            source = HardwareFrameSource(
                channels=config.channels,
                poll_interval_s=config.capture.poll_interval_s,
                hardware_serial=config.capture.hardware_serial,
                stop_event=stop_event,
            )
            hardware_counters = source.counters
            frame_iterator = source.captured_frames()
        else:
            try:
                gate_config = load_gate_config(GateConfig.default_path())
            except GateConfigError as exc:
                logger.critical(
                    "could not load gate config for --source synthetic: %s", exc
                )
                raise
            duration_s = (
                args.duration_s
                if args.duration_s is not None
                else DEFAULT_SYNTHETIC_DURATION_S
            )
            frame_iterator = _synthetic_frame_iterator(
                db=db,
                dictionary=dictionary,
                gate_config=gate_config,
                bracket_name=args.bracket,
                duration_s=duration_s,
                channel_name=config.channels[0].name,
            )

        if args.duration_s is not None:
            # A pure per-frame stop-event check on this thread is not
            # sufficient on its own: HardwareFrameSource.captured_frames()
            # blocks internally between polls and only re-checks the stop
            # event on its own schedule, so an independent thread is what
            # actually enforces the wall-clock bound on an idle bus.
            watchdog = threading.Timer(args.duration_s, stop_event.set)
            watchdog.daemon = True
            watchdog.name = "logger-duration-watchdog"
            watchdog.start()

        for captured in frame_iterator:
            if stop_event.is_set():
                break
            fan_out.submit(captured)
    except Exception:
        logger.critical(
            "capture terminated by an unhandled exception", exc_info=True
        )
    finally:
        if watchdog is not None:
            watchdog.cancel()

    stop_event.set()
    try:
        fan_out.archive_queue.put_nowait(ARCHIVE_RUNNER_STOP)
    except queue.Full:
        logger.warning(
            "archive queue full at shutdown -- the runner will still exit "
            "via the stop event"
        )

    archive_runner.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)
    telemetry_pipeline.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)
    link.close()

    archive_closed_cleanly = False
    try:
        writer.close()
        archive_closed_cleanly = (
            not fan_out.counters.archive_write_failure
            and not fan_out.counters.archive_overflow
        )
    except Exception:
        logger.critical("archive writer failed to close cleanly", exc_info=True)

    if archive_closed_cleanly:
        mark_done(session, writer)
        logger.info("session %s marked done", session.session_name)
    else:
        logger.warning(
            "session %s left WITHOUT a .done marker -- the archive did "
            "not close cleanly (archive_write_failure=%s archive_overflow=%s)",
            session.session_name,
            fan_out.counters.archive_write_failure,
            fan_out.counters.archive_overflow,
        )

    summary = _build_summary(
        session=session,
        config=config,
        args=args,
        fan_out_counters=fan_out.counters,
        pipeline_counters=telemetry_pipeline.counters,
        writer=writer,
        hardware_counters=hardware_counters,
        marked_done=archive_closed_cleanly,
        elapsed_s=time.monotonic() - start_t,
    )
    _log_human_summary(summary)
    print(json.dumps(summary, sort_keys=True))

    # Never interleaved with the archive-lifecycle ordering above -- the
    # heartbeat only observes state, it does not participate in it. This
    # plan's path is the clean one: 03-03 owns the unclean-exit terminal
    # state, so the status file is removed only when the archive itself
    # closed cleanly; otherwise it is left in place (still stale-detectable
    # by a later `telemetry-status` run) rather than erased.
    publisher.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)
    if archive_closed_cleanly:
        publisher.remove()

    return 0 if archive_closed_cleanly else 1


def main(argv=None) -> None:
    args = _parse_args(argv)
    _configure_logging(args.log_level)

    stop_event = threading.Event()
    # Installed before ANY other resource is constructed -- a signal
    # arriving mid-startup must never leave a half-built process with an
    # open archive and no way to unwind it (src/new_logger.py lines
    # 329-332's ordering).
    _install_signal_handlers(stop_event)

    try:
        config = load_logger_config(args.config)
    except LoggerConfigError as exc:
        logger.error("failed to load logger config at %s: %s", args.config, exc)
        raise SystemExit(1) from exc

    config = _apply_overrides(config, args)

    # Config load is the earliest point ops.heartbeat_path is known -- a
    # config failure above produces NO status file at all. That is honest:
    # the runbook (03-07) must say so, not invent a fallback path.
    publisher = HeartbeatPublisher(
        path=config.ops.heartbeat_path,
        interval_s=config.ops.heartbeat_interval_s,
        stop_event=stop_event,
        snapshot_fn=lambda: HeartbeatSnapshot(state=STATE_BOOTING, detail=None, extras={}),
    )
    publisher.publish_now(publisher.snapshot_fn())

    try:
        db = load_dbc(config.dbc_path)
    except DbcLoadError as exc:
        logger.error("failed to load DBC: %s", exc)
        raise SystemExit(1) from exc

    dictionary = build_id_dictionary(db, dbc_path=config.dbc_path)

    try:
        allowlist = resolve_allowlist(config, db)
    except LoggerConfigError as exc:
        logger.error("failed to resolve telemetry allowlist: %s", exc)
        raise SystemExit(1) from exc

    exit_code = _run_session(config, args, db, dictionary, allowlist, stop_event, publisher)
    if exit_code != 0:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
