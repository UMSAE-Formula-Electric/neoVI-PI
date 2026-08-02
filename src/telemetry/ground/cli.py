"""
telemetry.ground.cli — the headless ground-station entry point
(`python -m telemetry.ground.cli`), GND-01.

Phase 1's ground station is headless on purpose: no browser dashboard and no
WebSocket server live here — those are Phase 2 (GND-02..05), which grows
this same process into the one that also serves the browser. This CLI's
whole job is to prove the phase's headline claim end to end: a frame
captured on the car arrives here, decoded against the DBC, having crossed
batching, COBS+CRC framing, and the link — with no radio hardware anywhere
in the chain.

**A plain single-threaded loop, no asyncio** — `01-CONTEXT.md` locks that
for Phase 1; asyncio's value only appears in Phase 2 once this process
starts serving several browser clients at once.

**Both ends read the same `config/logger.json`** (OPS-05) — the dictionary,
the allowlist, and the encoder options must match on both sides, and a
mismatch there is a caller error, not something negotiated over the wire
(that negotiation is Phase 4 scope, per `dict_version`'s own docstring).

**The `udp` link is bound with a deliberate role reversal.** The car's
`UdpLink` binds `(local_host, local_port)` — its own outbound source
address — and sends to `(remote_host, remote_port)`. Since this station only
*receives* in Phase 1 (it never calls `link.send()`), it must bind to the
address the car is actually sending to, which is `(remote_host,
remote_port)` from the shared file's own naming. This is what lets one
checked-in file serve both ends when they run on two different machines
(the car's onboard box and the pit laptop) without needing a second config
file — `_build_link` below is the one place that role reversal is made
concrete, so it never needs re-deriving anywhere else.

**Decode happens here, never on the car** (PROJECT.md's architectural
inversion) — the car ships raw compressed frames; this station is where a
frame becomes a named signal with a value and a unit.

**Every layer's failure is caught by its specific type and counted, never
allowed to reach or kill this loop (T-01-01):** framing/CFR failures are
counted on `Deframer`'s own counters (`telemetry.ground.deframe`); a DBC
decode failure — an id the DBC does not describe, or a payload the DBC
itself rejects — is counted here and logged once per message id (repeats
suppressed, not re-logged, mirroring `telemetry.capture.fanout`'s and
`telemetry.logger.pipeline`'s established T-01-18 rate-limiting pattern).
This is a deliberate departure from `src/new_logger.py::writer_thread`'s
bare `except Exception: pass` (lines 244-247) — CAP-06/T-01-28 exist
specifically to eliminate that swallow, on the ground side as much as the
car side.

**Two outputs**, mirroring the car-side CLI's convention (stderr for
humans, stdout reserved for machine-readable output): decoded signal
records are newline-delimited JSON on stdout, one object per signal; a
link-health line — batches received, batches discarded by each failure
class, records decoded, and records that failed to decode — goes to stderr
on a fixed interval. These are the counters Phase 6's link-health indicator
(VIEW-06) will read, so they are named as they will be consumed, not for
this CLI's own convenience.

**A bounded `recv()` timeout and a stop-event check every iteration** mean a
silent or hostile link can never leave this process unkillable (T-01-29).
"""

import argparse
import json
import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Callable, Optional, Set

from cantools.database.errors import DecodeError as DbcDecodeError

from telemetry.ground.deframe import DeframeCounters, Deframer
from telemetry.ground.server import DashboardServer, SseHub
from telemetry.ground.state import GroundStateError, SignalState, build_message_index
from telemetry.link.base import Link
from telemetry.link.loopback import LoopbackLink
from telemetry.link.udp import UdpLink
from telemetry.logger.config import (
    VALID_LINK_KINDS,
    LoggerConfig,
    LoggerConfigError,
    load_logger_config,
)
from telemetry.measure.config import GateConfig, GateConfigError, load_gate_config
from telemetry.wire.dictionary import DbcLoadError, build_id_dictionary, load_dbc
from telemetry.wire.frame_source import RawFrame

logger = logging.getLogger(__name__)

DEFAULT_HEALTH_INTERVAL_S = 5.0
DEFAULT_RECV_TIMEOUT_S = 0.5


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
            "The headless ground-station consumer: receives the framed "
            "telemetry stream over the configured link, deframes it, and "
            "decodes every recovered frame against the DBC -- driven "
            "entirely from config/logger.json, the same file the car-side "
            "logger reads (GND-01, OPS-05)."
        )
    )
    parser.add_argument(
        "--config",
        default=str(LoggerConfig.default_path()),
        help="Path to the logger config (default: config/logger.json).",
    )
    parser.add_argument(
        "--link-kind",
        default=None,
        choices=sorted(VALID_LINK_KINDS),
        help="Override link.kind from the config.",
    )
    parser.add_argument(
        "--output-file",
        default=None,
        help=(
            "Also append every decoded record to this file, one JSON "
            "object per line (stdout always carries every record either way)."
        ),
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=None,
        help=(
            "Bound the run to N seconds (default: run until interrupted). "
            "Production runs unbounded, stopped by SIGINT/SIGTERM; this "
            "flag exists primarily so tests can run this CLI as a bounded "
            "subprocess with no reliance on platform-specific signal delivery."
        ),
    )
    parser.add_argument(
        "--health-interval-s",
        type=float,
        default=DEFAULT_HEALTH_INTERVAL_S,
        help=f"Seconds between link-health lines on stderr (default {DEFAULT_HEALTH_INTERVAL_S}).",
    )
    parser.add_argument(
        "--recv-timeout-s",
        type=float,
        default=DEFAULT_RECV_TIMEOUT_S,
        help=(
            "Bound on each link.recv() call, so a silent link is re-checked "
            f"against the stop event promptly (default {DEFAULT_RECV_TIMEOUT_S})."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help=(
            "Also serve the live dashboard over HTTP/SSE alongside the "
            "existing headless JSON output (GND-02). The gate config and a "
            "DBC message index are only loaded when this flag is set -- "
            "the headless path is unaffected either way."
        ),
    )
    parser.add_argument(
        "--http-host",
        default="127.0.0.1",
        help=(
            "Host to bind the dashboard HTTP server to when --serve is set "
            "(default: 127.0.0.1, loopback-only). Binding a non-loopback "
            "address publishes unauthenticated live vehicle telemetry to "
            "everyone on that network -- this server has no authentication "
            "of any kind."
        ),
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=8080,
        help="Port to bind the dashboard HTTP server to when --serve is set (default: 8080).",
    )
    return parser.parse_args(argv)


def _build_link(link_config) -> Link:
    """See the module docstring's "deliberate role reversal" note: this
    station binds `(remote_host, remote_port)`, not `(local_host,
    local_port)` -- the address the car is configured to send to. No
    `remote_addr` is configured here; this station never sends
    (Phase 1's GND-01 scope is receive-only)."""
    if link_config.kind == "loopback":
        return LoopbackLink()
    if link_config.kind == "udp":
        return UdpLink(
            local_addr=(link_config.udp.remote_host, link_config.udp.remote_port),
            remote_addr=None,
            recv_bufsize=link_config.udp.recv_bufsize,
        )
    # Unreachable in practice -- telemetry.logger.config already restricts
    # link.kind to VALID_LINK_KINDS at load time.
    raise LoggerConfigError(
        f"link.kind={link_config.kind!r} is not one of {sorted(VALID_LINK_KINDS)}"
    )


class UndecodableFrame(Exception):
    """Raised when a recovered `RawFrame`'s message id is not described by
    the DBC, or its payload fails a DBC-level decode (e.g. a length the DBC
    itself rejects). Caught and counted by `run_consumer_loop` -- never
    allowed to reach or kill the loop (T-01-01, T-01-28). Distinct from
    `telemetry.wire.decoder.DecodeError`, which `Deframer` already catches
    one layer further upstream (CFR recovery, not DBC decode)."""


def _decode_frame(db, frame: RawFrame):
    """Resolve `frame` against the DBC and decode its payload into signal
    values. Raises `UndecodableFrame` -- never a raw `cantools` exception --
    so callers have exactly one exception type to catch."""
    try:
        message = db.get_message_by_frame_id(
            frame.frame_id, force_extended_id=frame.is_extended
        )
    except KeyError as exc:
        raise UndecodableFrame(
            f"frame_id=0x{frame.frame_id:X} is_extended={frame.is_extended} "
            f"is not described by the DBC"
        ) from exc
    try:
        signals = message.decode(frame.payload)
    except DbcDecodeError as exc:
        raise UndecodableFrame(
            f"{message.name} (frame_id=0x{frame.frame_id:X}) payload could "
            f"not be decoded: {exc}"
        ) from exc
    return message, signals


def _signal_unit(message, signal_name: str) -> Optional[str]:
    signal_def = message.get_signal_by_name(signal_name)
    return signal_def.unit or None


@dataclass
class GroundConsumerCounters:
    """Link-health counters this CLI's own DBC-decode layer adds beyond
    `DeframeCounters` -- DBC decode happens one layer further in than
    framing/CFR recovery, so it gets its own named counters (T-01-28),
    reported alongside the deframer's in the periodic link-health line.
    Named as Phase 6's link-health indicator (VIEW-06) will read them, not
    for this CLI's own convenience."""

    batches_received: int = 0
    records_dbc_decoded: int = 0
    records_dbc_decode_failed: int = 0
    # Per-message-id log rate limiting (T-01-18, mirroring FanOutCounters'
    # telemetry_error_log_suppressed_count): every suppressed repeat is
    # still counted here, so nothing is actually lost even though it isn't
    # re-logged.
    records_dbc_decode_log_suppressed_count: int = 0
    # A link-layer OSError beyond the platform-specific cases UdpLink.recv()
    # already contains (e.g. an unexpected socket condition) -- counted and
    # treated exactly like a timeout so it can never take the loop down
    # (T-01-01, T-01-29).
    link_recv_error_count: int = 0


def _json_default(value):
    """`cantools` choice-decoded signals come back as `NamedSignalValue`,
    which `json.dumps` does not know how to serialize -- stringify anything
    `json` cannot handle natively rather than letting a decoded enum crash
    record emission."""
    return str(value)


def _emit_record(out_stream: IO[str], output_file: Optional[IO[str]], **fields) -> None:
    line = json.dumps(fields, sort_keys=True, default=_json_default)
    print(line, file=out_stream, flush=True)
    if output_file is not None:
        output_file.write(line + "\n")
        output_file.flush()


def _emit_health(
    deframe_counters: DeframeCounters,
    ground_counters: GroundConsumerCounters,
    elapsed_s: float,
) -> None:
    logger.info(
        "link-health: batches_received=%d batches_ok=%d "
        "discarded[cobs=%d crc=%d batch_format=%d buffer_overflow=%d] "
        "records_decoded=%d records_decode_failed=%d "
        "link_recv_errors=%d elapsed_s=%.1f",
        ground_counters.batches_received,
        deframe_counters.batches_ok,
        deframe_counters.cobs_failures,
        deframe_counters.crc_failures,
        deframe_counters.batch_format_failures,
        deframe_counters.buffer_overflow_count,
        ground_counters.records_dbc_decoded,
        ground_counters.records_dbc_decode_failed,
        ground_counters.link_recv_error_count,
        elapsed_s,
    )


def _decode_and_emit(
    db,
    frame: RawFrame,
    counters: GroundConsumerCounters,
    logged_undecodable_ids: Set[int],
    on_record: Callable[..., None],
) -> None:
    try:
        message, signals = _decode_frame(db, frame)
    except UndecodableFrame as exc:
        counters.records_dbc_decode_failed += 1
        if frame.frame_id in logged_undecodable_ids:
            counters.records_dbc_decode_log_suppressed_count += 1
        else:
            logged_undecodable_ids.add(frame.frame_id)
            logger.warning(
                "undecodable record (frame_id=0x%X is_extended=%s "
                "timestamp_us=%d): %s -- further occurrences of this frame "
                "id are counted, not re-logged",
                frame.frame_id,
                frame.is_extended,
                frame.timestamp_us,
                exc,
            )
        return

    counters.records_dbc_decoded += 1
    for signal_name, value in signals.items():
        on_record(
            topic=f"/can/{message.name}",
            message_id=frame.frame_id,
            message_name=message.name,
            signal=signal_name,
            value=value,
            unit=_signal_unit(message, signal_name),
            timestamp_us=frame.timestamp_us,
        )


def run_consumer_loop(
    *,
    link: Link,
    deframer: Deframer,
    db,
    stop_event: threading.Event,
    on_record: Callable[..., None],
    counters: Optional[GroundConsumerCounters] = None,
    recv_timeout_s: float = DEFAULT_RECV_TIMEOUT_S,
    health_interval_s: float = DEFAULT_HEALTH_INTERVAL_S,
    now_fn: Callable[[], float] = time.monotonic,
) -> GroundConsumerCounters:
    """The ground station's receive-decode-emit loop (GND-01) -- the reusable
    core `main()` wires CLI args into, and what Task 1's tests drive directly
    against a `LoopbackLink` with no CLI or subprocess involved.

    Runs until `stop_event` is set. `recv_timeout_s` bounds every
    `link.recv()` call so the stop event is re-checked promptly even when
    the link is silent (T-01-29) -- a terminated session can never hang this
    process. Emits one link-health line (`_emit_health`) every
    `health_interval_s`, and always emits one final line on exit so a
    bounded run's last word is a real summary, not silence.

    Every failure this loop's own layer can produce (an undescribed message
    id, a DBC-level decode failure, an unexpected link-recv `OSError`) is
    caught by its specific type, counted on the returned
    `GroundConsumerCounters`, and never allowed to propagate out of this
    function (T-01-01). Framing/CFR failures are `Deframer.feed`'s own
    responsibility and are never re-caught here.
    """
    counters = counters if counters is not None else GroundConsumerCounters()
    logged_undecodable_ids: Set[int] = set()
    start_t = now_fn()
    last_health_t = start_t

    while not stop_event.is_set():
        try:
            data = link.recv(timeout=recv_timeout_s)
        except OSError as exc:
            counters.link_recv_error_count += 1
            logger.warning("link recv error: %s -- treated as no data this call", exc)
            data = None

        if data is not None:
            counters.batches_received += 1
            for recovered_batch in deframer.feed(data):
                for frame in recovered_batch:
                    _decode_and_emit(db, frame, counters, logged_undecodable_ids, on_record)

        now = now_fn()
        if now - last_health_t >= health_interval_s:
            _emit_health(deframer.counters, counters, elapsed_s=now - start_t)
            last_health_t = now

    _emit_health(deframer.counters, counters, elapsed_s=now_fn() - start_t)
    return counters


def main(argv=None) -> None:
    args = _parse_args(argv)
    _configure_logging(args.log_level)

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    try:
        config = load_logger_config(args.config)
    except LoggerConfigError as exc:
        logger.error("failed to load logger config at %s: %s", args.config, exc)
        raise SystemExit(1) from exc

    if args.link_kind is not None:
        config = replace(config, link=replace(config.link, kind=args.link_kind))

    try:
        db = load_dbc(config.dbc_path)
    except DbcLoadError as exc:
        logger.error("failed to load DBC: %s", exc)
        raise SystemExit(1) from exc

    dictionary = build_id_dictionary(db, dbc_path=config.dbc_path)
    link = _build_link(config.link)
    deframer = Deframer(dictionary)

    if isinstance(link, UdpLink):
        host, port = link.local_addr
        logger.info("ground station listening on udp://%s:%d", host, port)
    else:
        logger.info(
            "ground station running against a %r link (in-process only, "
            "no separate car process can reach it)",
            config.link.kind,
        )

    # Serving-mode setup: the gate config and the DBC message index are
    # only loaded when --serve is set (D-04) -- the headless path must
    # behave exactly as before, including not loading the gate config at
    # all.
    signal_state: Optional[SignalState] = None
    sse_hub: Optional[SseHub] = None
    if args.serve:
        try:
            gate_config = load_gate_config(GateConfig.default_path())
        except GateConfigError as exc:
            logger.error("failed to load gate config: %s", exc)
            raise SystemExit(1) from exc
        try:
            message_index = build_message_index(db, config, gate_config)
        except GroundStateError as exc:
            logger.error("failed to build ground station message index: %s", exc)
            raise SystemExit(1) from exc
        signal_state = SignalState(message_index)
        sse_hub = SseHub()

    output_file: Optional[IO[str]] = None
    if args.output_file is not None:
        output_file = open(Path(args.output_file), "a", encoding="utf-8")

    watchdog: Optional[threading.Timer] = None
    if args.duration_s is not None:
        watchdog = threading.Timer(args.duration_s, stop_event.set)
        watchdog.daemon = True
        watchdog.name = "ground-duration-watchdog"
        watchdog.start()

    def on_record(**fields) -> None:
        _emit_record(sys.stdout, output_file, **fields)  # unchanged, GND output survives
        if signal_state is not None and sse_hub is not None:
            payload = signal_state.update(
                message_name=fields["message_name"],
                signal=fields["signal"],
                value=fields["value"],
                unit=fields["unit"],
                now_ms=int(time.time() * 1000),
            )
            sse_hub.broadcast(payload)

    dashboard_server: Optional[DashboardServer] = None
    if args.serve:
        # Constructed after signal handlers are already installed
        # (preserving the handlers-before-resources ordering `main()`
        # already has at the top of this function).
        dashboard_server = DashboardServer(
            host=args.http_host,
            port=args.http_port,
            hub=sse_hub,
            snapshot_provider=signal_state.snapshot,
        )
        logger.info(
            "ground station dashboard serving on http://%s:%d%s",
            args.http_host,
            dashboard_server.port,
            "/events",
        )

    consumer_counters_holder: dict = {}

    if dashboard_server is not None:

        def _run_consumer_and_stop_server() -> None:
            # This is the ONLY thread from which `dashboard_server.shutdown()`
            # is safe to call (02-RESEARCH.md Pattern 4 / Pitfall 3): calling
            # it from the SIGINT/SIGTERM handler deadlocks, because that
            # handler runs on the main thread, which is the same thread
            # blocked inside `serve_forever()` below.
            try:
                consumer_counters_holder["counters"] = run_consumer_loop(
                    link=link,
                    deframer=deframer,
                    db=db,
                    stop_event=stop_event,
                    on_record=on_record,
                    recv_timeout_s=args.recv_timeout_s,
                    health_interval_s=args.health_interval_s,
                )
            finally:
                dashboard_server.shutdown()

        consumer_thread = threading.Thread(
            target=_run_consumer_and_stop_server, name="ground-consumer", daemon=False
        )
        try:
            consumer_thread.start()
            dashboard_server.serve_forever()  # blocks the main thread
        finally:
            consumer_thread.join()
            dashboard_server.server_close()
            if watchdog is not None:
                watchdog.cancel()
            link.close()
            if output_file is not None:
                output_file.close()
        counters = consumer_counters_holder.get("counters", GroundConsumerCounters())
    else:
        # Headless mode: the loop runs inline on the main thread, exactly
        # as before, with no threading change at all.
        try:
            counters = run_consumer_loop(
                link=link,
                deframer=deframer,
                db=db,
                stop_event=stop_event,
                on_record=on_record,
                recv_timeout_s=args.recv_timeout_s,
                health_interval_s=args.health_interval_s,
            )
        finally:
            if watchdog is not None:
                watchdog.cancel()
            link.close()
            if output_file is not None:
                output_file.close()

    logger.info(
        "ground station stopped: batches_received=%d records_dbc_decoded=%d "
        "records_dbc_decode_failed=%d",
        counters.batches_received,
        counters.records_dbc_decoded,
        counters.records_dbc_decode_failed,
    )


if __name__ == "__main__":
    main()
